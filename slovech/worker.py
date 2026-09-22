"""Durable single-host worker; jobs are leased and processing is at least once."""

import asyncio
import json
import logging
import signal
import time
from datetime import UTC, datetime
from html import escape
from pathlib import Path

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from slovech.ai.services import generate_summary_with_openrouter, transcribe_audio_with_gemini
from slovech.core.config import get_settings
from slovech.core.logging import configure_logging
from slovech.core.models import Lecture
from slovech.core.process import run_process
from slovech.core.runtime import process_lock
from slovech.core.storage import Repository
from slovech.core.telegram import create_bot
from slovech.core.youtube import download_youtube_audio, fetch_youtube_transcript

logger = logging.getLogger(__name__)


class BoundedDownload:
    """Stop Telegram downloads even when upstream file_size metadata is wrong."""

    def __init__(self, path: Path, maximum: int):
        self.file = path.open("wb")
        self.maximum = maximum
        self.size = 0

    def write(self, chunk):
        self.size += len(chunk)
        if self.size > self.maximum:
            raise ValueError("Audio exceeds configured size limit")
        return self.file.write(chunk)

    def seek(self, *args):
        return self.file.seek(*args)

    def flush(self):
        self.file.flush()

    def close(self):
        self.file.close()


async def notify(bot, job, lecture, settings):
    keyboard = [
        [
            InlineKeyboardButton(
                text="Открыть конспект",
                web_app=WebAppInfo(url=f"{settings.domain}/app?v=10&id={lecture.id}"),
            )
        ],
        [InlineKeyboardButton(text="Скачать DOCX", callback_data=f"dl_ru_{lecture.id}")],
    ]
    if lecture.language == "en":
        keyboard.append(
            [
                InlineKeyboardButton(
                    text="Скачать оригинал (EN)", callback_data=f"dl_en_{lecture.id}"
                )
            ]
        )
    try:
        await bot.edit_message_text(
            chat_id=job["payload"]["chat_id"],
            message_id=job["payload"]["status_id"],
            text=f"🌿 <b>{escape(lecture.title)}</b>\nКонспект готов.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
        )
    except TelegramBadRequest as exc:
        # Replaying an acknowledged edit is a successful idempotent notification.
        if "message is not modified" not in exc.message.lower():
            raise


async def process_job(job: dict, bot, repository: Repository):
    settings = repository.settings
    lecture = await asyncio.to_thread(repository.get, job["id"], job["user_id"])
    if lecture:
        await notify(bot, job, lecture, settings)
        return
    payload = job["payload"]
    # Attempt-specific files prevent an expired lease from modifying a new attempt's media.
    stem = f"{job['id']}_{job['attempts']}"
    raw = settings.audio_dir / f"raw_{stem}"
    final = settings.audio_dir / f"{stem}.mp3"
    saved = False
    telegram_source = None
    try:
        transcription = None
        if payload["kind"] == "youtube":
            transcription = await fetch_youtube_transcript(payload["video_id"])
            if not transcription:
                await download_youtube_audio(payload["url"], str(raw))
        else:
            info = await bot.get_file(payload["file_id"])
            if not info.file_path or (
                info.file_size and info.file_size > settings.max_upload_bytes
            ):
                raise ValueError("Audio too large or unavailable")
            if settings.telegram_local_file_root is not None:
                source = Path(info.file_path)
                if (
                    not source.resolve().is_relative_to(settings.telegram_local_file_root.resolve())
                    or source.is_symlink()
                ):
                    raise ValueError("Telegram file is outside the shared root")
                telegram_source = source
            stream = BoundedDownload(raw, settings.max_upload_bytes)
            try:
                await bot.download_file(info.file_path, stream, timeout=300)
            finally:
                stream.close()
        if not transcription:
            if not raw.is_file() or not 0 < raw.stat().st_size <= settings.max_upload_bytes:
                raise ValueError("Downloaded audio exceeds size limit or is missing")
            probe = await run_process(
                "ffprobe",
                "-v",
                "error",
                "-protocol_whitelist",
                "file,pipe",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                str(raw),
                timeout=30,
            )
            duration = float(json.loads(probe)["format"]["duration"])
            if not 0 < duration <= settings.max_audio_seconds:
                raise ValueError("Audio exceeds duration limit")
            await run_process(
                "ffmpeg",
                "-nostdin",
                "-y",
                "-v",
                "error",
                "-protocol_whitelist",
                "file,pipe",
                "-i",
                str(raw),
                "-vn",
                "-ar",
                "16000",
                "-ac",
                "1",
                "-b:a",
                "64k",
                "-t",
                str(settings.max_audio_seconds),
                "-fs",
                str(settings.max_upload_bytes),
                str(final),
            )
            if not final.is_file() or final.stat().st_size >= settings.max_upload_bytes:
                raise ValueError("Converted audio exceeds size limit")
            transcription = await transcribe_audio_with_gemini(str(final))
        language = "en" if transcription.startswith("[LANG:EN]") else "ru"
        transcription = transcription.removeprefix("[LANG:EN]").removeprefix("[LANG:RU]").strip()
        summary = await generate_summary_with_openrouter(transcription, language)
        lecture = Lecture(
            **summary,
            id=job["id"],
            user_id=job["user_id"],
            created_at=datetime.now(UTC).isoformat(),
            transcription=transcription,
            language=language,
            audio_url=f"/audio/{final.name}" if final.is_file() else None,
        )
        repository.save(lecture)
        saved = True
        await notify(bot, job, lecture, settings)
    finally:
        for path in settings.audio_dir.glob(f"raw_{stem}*"):
            path.unlink(missing_ok=True)
        if not saved:
            final.unlink(missing_ok=True)
        if telegram_source is not None and (saved or job.get("attempts", 0) >= 3):
            telegram_source.unlink(missing_ok=True)


async def run_worker(stop: asyncio.Event):
    settings = get_settings()
    settings.validate_worker()
    repository = Repository(settings)
    repository.initialize()
    repository.recover_running()
    bot = create_bot(settings)

    async def heartbeat():
        while not stop.is_set():
            (settings.data_dir / "worker.heartbeat").write_text(str(time.time()))
            await asyncio.sleep(15)

    heart = asyncio.create_task(heartbeat())
    try:
        while not stop.is_set():
            job = await asyncio.to_thread(repository.claim)
            if not job:
                try:
                    await asyncio.wait_for(stop.wait(), 2)
                except TimeoutError:
                    pass
                continue
            logger.info("Job started id=%s attempt=%s", job["id"], job["attempts"])
            try:
                await asyncio.wait_for(
                    process_job(job, bot, repository), settings.job_timeout_seconds
                )
            except Exception as exc:
                # Never store provider response bodies, tokens or transcript contents in logs.
                error = type(exc).__name__
                logger.error("Job failed id=%s type=%s", job["id"], error)
                await asyncio.to_thread(repository.finish, job, error)
                if job["attempts"] >= 3:
                    try:
                        await bot.edit_message_text(
                            chat_id=job["payload"]["chat_id"],
                            message_id=job["payload"]["status_id"],
                            text=f"Не удалось обработать запись. Повторите отправку. Код: {job['id'][:8]}",
                        )
                    except Exception:
                        logger.warning("Failure notification unavailable id=%s", job["id"])
            else:
                await asyncio.to_thread(repository.finish, job)
                logger.info("Job completed id=%s", job["id"])
    finally:
        heart.cancel()
        await asyncio.gather(heart, return_exceptions=True)
        await bot.session.close()


async def main():
    configure_logging()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    settings = get_settings()
    settings.prepare()
    lock = process_lock(settings.data_dir / "worker.lock")
    lock.__enter__()
    task = asyncio.create_task(run_worker(stop))

    def shutdown():
        stop.set()
        # Cancel work promptly; expired leases recover unfinished jobs after restart.
        task.cancel()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, shutdown)
    try:
        await task
    except asyncio.CancelledError:
        pass
    finally:
        lock.__exit__(None, None, None)


if __name__ == "__main__":
    asyncio.run(main())
