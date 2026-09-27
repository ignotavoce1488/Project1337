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

from slovech.ai.aitunnel import (
    FALLBACK_MODEL,
    MAX_FILE_BYTES,
    MODEL,
    TranscriptionHTTPError,
    transcribe_audio_with_aitunnel,
)
from slovech.ai.services import (
    ProviderError,
    SummaryUnavailable,
    generate_formatted_transcription_with_openrouter,
    generate_summary_with_openrouter,
    paragraphize_transcription,
    translate_summary_with_openrouter,
    translate_transcription_chunk_with_openrouter,
    translation_chunks,
)
from slovech.core.config import get_settings
from slovech.core.logging import configure_logging
from slovech.core.models import Lecture
from slovech.core.privacy import clean_crash_residue, complete_deletions, sweep_retention
from slovech.core.process import run_process
from slovech.core.runtime import process_lock
from slovech.core.storage import ProcessingCancelled, Repository
from slovech.core.telegram import create_bot
from slovech.core.youtube import download_youtube_audio, fetch_youtube_transcript

logger = logging.getLogger(__name__)
# Split by duration even when the compressed file fits: providers may reject
# hour-long audio while accepting the same recording in short segments.
TRANSCRIPTION_CHUNK_SECONDS = 8 * 60


class LegalAcceptanceRequired(Exception):
    """The owner has not accepted the current documents."""


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


async def transcribe_audio(
    final: Path,
    duration: float,
    job_id: str | None = None,
    repository: Repository | None = None,
    language_hint: str | None = None,
) -> str:
    disabled_models: set[str] = set()

    async def transcribe_part(path: Path) -> str:
        last_error: ProviderError | None = None
        for model in (MODEL, FALLBACK_MODEL):
            if model in disabled_models:
                continue
            if repository is not None and job_id is not None:
                repository.ensure_transcription_allowed(job_id)
            try:
                return await transcribe_audio_with_aitunnel(
                    str(path), model=model, language_hint=language_hint
                )
            except ProviderError as exc:
                if isinstance(exc, TranscriptionHTTPError) and exc.status_code == 400 and language_hint:
                    logger.warning("Transcription hint rejected; retrying automatic detection model=%s", model)
                    try:
                        return await transcribe_audio_with_aitunnel(str(path), model=model)
                    except ProviderError as retry_exc:
                        exc = retry_exc
                last_error = exc
                if isinstance(exc, TranscriptionHTTPError) and exc.status_code == 429:
                    disabled_models.add(model)
                logger.warning("Transcription model unavailable model=%s", model)
        raise last_error or ProviderError("No transcription model available")

    try:
        if duration <= TRANSCRIPTION_CHUNK_SECONDS and final.stat().st_size < MAX_FILE_BYTES:
            cached = (
                repository.get_transcription_part(job_id, 0)
                if repository is not None and job_id is not None
                else None
            )
            if cached is not None:
                return cached
            text = await transcribe_part(final)
            if repository is not None and job_id is not None:
                repository.save_transcription_part(job_id, 0, text)
            return text

        pattern = final.with_name(f"{final.stem}_part_%03d.mp3")
        await run_process(
            "ffmpeg",
            "-nostdin",
            "-y",
            "-v",
            "error",
            "-i",
            str(final),
            "-f",
            "segment",
            "-segment_time",
            str(TRANSCRIPTION_CHUNK_SECONDS),
            "-reset_timestamps",
            "1",
            "-vn",
            "-c:a",
            "copy",
            str(pattern),
            timeout=max(120, duration / 8),
        )
        parts = sorted(final.parent.glob(f"{final.stem}_part_*.mp3"))
        if not parts:
            raise ValueError("Audio chunking produced no files")
        # FFmpeg can emit a sub-second trailing fragment at an exact boundary.
        if len(parts) > 1 and parts[-1].stat().st_size < 8192:
            probe = await run_process(
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                str(parts[-1]),
                timeout=30,
            )
            if float(json.loads(probe)["format"]["duration"]) < 1:
                parts.pop().unlink(missing_ok=True)
        if not all(0 < part.stat().st_size < MAX_FILE_BYTES for part in parts):
            raise ValueError("Transcription segment exceeds provider size limit")
        transcripts = []
        script_counts = {"ru": 0, "en": 0}
        detected_languages: dict[str, int] = {}
        for index, part in enumerate(parts):
            text = (
                repository.get_transcription_part(job_id, index)
                if repository is not None and job_id is not None
                else None
            )
            if text is None:
                text = await transcribe_part(part)
                if repository is not None and job_id is not None:
                    repository.save_transcription_part(job_id, index, text)
            logger.info("Transcription part ready job=%s part=%s/%s", job_id, index + 1, len(parts))
            if text.startswith("[LANG:") and "\n" in text:
                code = text.split("\n", 1)[0][6:-1].lower()
                detected_languages[code] = detected_languages.get(code, 0) + 1
            content = text.split("\n", 1)[1].strip() if text.startswith("[LANG:") and "\n" in text else text.strip()
            script_counts["ru"] += sum(
                "а" <= char.lower() <= "я" or char.lower() == "ё" for char in content
            )
            script_counts["en"] += sum("a" <= char.lower() <= "z" for char in content)
            transcripts.append(content)
        detected = max(detected_languages, key=detected_languages.get) if detected_languages else (
            "en" if script_counts["en"] > script_counts["ru"] else "ru"
        )
        language = f"[LANG:{(language_hint or detected).upper()}]"
        return f"{language}\n" + "\n\n".join(transcripts)
    finally:
        for part in final.parent.glob(f"{final.stem}_part_*.mp3"):
            part.unlink(missing_ok=True)


async def notify(bot, job, lecture, settings, repository: Repository | None = None):
    if repository is not None and repository.result_message_id(job["id"]):
        return
    from slovech.core.languages import bot_copy

    preference = repository.get_preferences(lecture.user_id) if repository is not None else {}
    locale = preference.get("interface_language") or "ru"
    translated = bool(lecture.translation_language == locale and lecture.summary_translated)
    primary_language = locale if translated else ("ru" if locale == "ru" and lecture.summary_ru else "orig")
    display_title = lecture.title_translated if translated else (
        lecture.title_ru if primary_language == "ru" and lecture.summary_ru else lecture.title
    )
    keyboard = [
        [
            InlineKeyboardButton(
                text=bot_copy(locale, 5),
                web_app=WebAppInfo(url=f"{settings.domain}/app?v=13&id={lecture.id}"),
            )
        ],
        [InlineKeyboardButton(text=bot_copy(locale, 6),
                              callback_data=f"dl_{primary_language}_{lecture.id}")],
    ]
    if translated or (lecture.language == "en" and locale == "ru"):
        keyboard.append(
            [
                InlineKeyboardButton(
                    text="Original DOCX", callback_data=f"dl_orig_{lecture.id}"
                )
            ]
        )
    sent = await bot.send_message(
        chat_id=job["payload"]["chat_id"],
        text=f"🌿 <b>{escape(display_title or lecture.title)}</b>\n{bot_copy(locale, 4)}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
    )
    if repository is not None:
        repository.record_result_message(job["id"], sent.message_id)
    try:
        await bot.edit_message_text(
            chat_id=job["payload"]["chat_id"],
            message_id=job["payload"]["status_id"],
            text="✅ " + bot_copy(locale, 7),
        )
    except TelegramBadRequest as exc:
        # The separate result was delivered even if the old status cannot be edited.
        if "message is not modified" not in exc.message.lower():
            logger.warning("Queue status edit unavailable id=%s", job.get("id"))


async def process_job(job: dict, bot, repository: Repository):
    settings = repository.settings
    repository.ensure_processing_allowed(job)
    if settings.legal_enforcement and (
        await asyncio.to_thread(repository.legal_stage, job["user_id"]) != "ready"
    ):
        raise LegalAcceptanceRequired()
    if job["payload"].get("kind") == "transcript_translation":
        lecture = await asyncio.to_thread(
            repository.get, job["payload"]["lecture_id"], job["user_id"]
        )
        if not lecture:
            raise ProcessingCancelled()
        target = job["payload"]["target_language"]
        if lecture.language == target or (
            lecture.transcription_translation_language == target and lecture.transcription_translated
        ):
            return
        chunks = translation_chunks(lecture.transcription, limit=4000)
        if not chunks:
            raise SummaryUnavailable("Transcript is empty")
        translated_parts = []
        for index, chunk in enumerate(chunks):
            repository.ensure_processing_allowed(job)
            translated = await asyncio.to_thread(repository.get_transcription_part, job["id"], index)
            if translated is None:
                translated = await translate_transcription_chunk_with_openrouter(chunk, target)
                await asyncio.to_thread(repository.save_transcription_part, job["id"], index, translated)
            translated_parts.append(translated)
        await asyncio.to_thread(
            repository.save_transcript_translation, job, "\n\n".join(translated_parts)
        )
        return
    if job["payload"].get("kind") == "translation":
        lecture = await asyncio.to_thread(
            repository.get, job["payload"]["lecture_id"], job["user_id"]
        )
        if not lecture:
            raise ProcessingCancelled()
        target = job["payload"]["target_language"]
        if lecture.language == target or (
            lecture.translation_language == target and lecture.summary_translated
        ):
            return
        if target == "ru" and lecture.language == "en" and lecture.summary_ru:
            translated = {
                "source_language": "en", "translation_language": "ru",
                "title_translated": lecture.title_ru or lecture.title,
                "summary_translated": lecture.summary_ru,
                "key_points_translated": lecture.key_points_ru or lecture.key_points,
            }
        else:
            translated = await translate_summary_with_openrouter(lecture.model_dump(), target)
        await asyncio.to_thread(repository.save_translation, job, translated)
        return
    lecture = await asyncio.to_thread(repository.get, job["id"], job["user_id"])
    if lecture:
        await notify(bot, job, lecture, settings, repository)
        return
    payload = job["payload"]
    # Attempt-specific files prevent an expired lease from modifying a new attempt's media.
    stem = f"{job['id']}_{job['attempts']}"
    raw = settings.audio_dir / f"raw_{stem}"
    final = settings.audio_dir / f"{stem}.mp3"
    telegram_source = None
    try:
        transcription = None
        if payload["kind"] == "youtube":
            transcription = await fetch_youtube_transcript(payload["video_id"], payload.get("language_hint"))
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
                repository.track_temporary_media(job, str(source))
            stream = BoundedDownload(raw, settings.max_upload_bytes)
            try:
                await bot.download_file(info.file_path, stream, timeout=300)
            finally:
                stream.close()
            if telegram_source is not None:
                telegram_source.unlink(missing_ok=True)
                telegram_source = None
                repository.forget_temporary_media(job["id"])
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
            transcription = await transcribe_audio(
                final, duration, job["id"], repository, payload.get("language_hint")
            )
            raw.unlink(missing_ok=True)
            final.unlink(missing_ok=True)
        language = payload.get("language_hint") or "ru"
        if transcription.startswith("[LANG:"):
            marker, _, remaining = transcription.partition("\n")
            code = marker[6:-1].lower() if marker.endswith("]") else ""
            if len(code) == 2 and code.isalpha():
                language = payload.get("language_hint") or code
                transcription = remaining
        if payload["kind"] == "audio" and not payload.get("language_hint"):
            # Script-based tags cannot distinguish English from most European languages.
            # Let the summary model follow the transcript's actual language.
            language = "auto"
        transcription = transcription.strip()
        repository.ensure_processing_allowed(job)
        from slovech.core.languages import LANGUAGES

        preferred = repository.get_preferences(job["user_id"])["interface_language"]
        target_language = payload.get("output_language") or preferred
        if target_language not in LANGUAGES:
            target_language = None
        generation_language = "auto" if language == "en" and target_language != "ru" else language
        summary = await generate_summary_with_openrouter(transcription, generation_language)
        if language == "en" and target_language == "ru" and summary.get("summary_ru"):
            summary.update(
                translation_language="ru", title_translated=summary.get("title_ru"),
                summary_translated=summary["summary_ru"],
                key_points_translated=summary.get("key_points_ru"),
            )
        elif target_language and (language == "auto" or language != target_language):
            try:
                repository.ensure_processing_allowed(job)
                translated = await translate_summary_with_openrouter(summary, target_language)
                detected = translated.pop("source_language", None)
                if language == "auto" and isinstance(detected, str) and len(detected) == 2 and detected.isalpha():
                    language = detected.lower()
                summary.update(translated)
            except ProcessingCancelled:
                raise
            except Exception:
                logger.warning("Summary translation unavailable id=%s target=%s", job["id"], target_language)
        lecture = Lecture(
            **summary,
            id=job["id"],
            user_id=job["user_id"],
            created_at=datetime.now(UTC).isoformat(),
            transcription=transcription,
            formatted_transcription=None,
            language=language,
            audio_url=None,
        )
        repository.save(lecture, job=job)
        repository.clear_transcription_parts(job["id"])
        repository.ensure_processing_allowed(job)
        await notify(bot, job, lecture, settings, repository)
        # The optional display formatting must never delay the finished summary.
        try:
            repository.ensure_processing_allowed(job)
            formatted = await asyncio.wait_for(
                generate_formatted_transcription_with_openrouter(transcription, language),
                timeout=240,
            )
            repository.update_formatted_transcription(
                lecture.model_copy(update={"formatted_transcription": formatted})
            )
        except ProcessingCancelled:
            raise
        except Exception:
            logger.warning("Optional transcript formatting unavailable id=%s", job["id"])
            repository.ensure_processing_allowed(job)
            repository.update_formatted_transcription(
                lecture.model_copy(
                    update={"formatted_transcription": paragraphize_transcription(transcription)}
                )
            )
    finally:
        for path in settings.audio_dir.glob(f"raw_{stem}*"):
            path.unlink(missing_ok=True)
        final.unlink(missing_ok=True)
        if telegram_source is not None:
            telegram_source.unlink(missing_ok=True)
            repository.forget_temporary_media(job["id"])


async def run_job_guarded(job: dict, bot, repository: Repository):
    """Observe deletion while HTTP/ffmpeg is in flight; always await cancellation cleanup."""
    task = asyncio.create_task(process_job(job, bot, repository))
    try:
        async with asyncio.timeout(repository.settings.job_timeout_seconds):
            while not task.done():
                repository.ensure_processing_allowed(job)
                await asyncio.wait({task}, timeout=0.25)
            await task
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def run_worker(stop: asyncio.Event):
    settings = get_settings()
    settings.validate_worker()
    repository = Repository(settings)
    repository.initialize()
    clean_crash_residue(repository)
    repository.recover_running()
    bot = create_bot(settings)

    async def heartbeat():
        while not stop.is_set():
            (settings.data_dir / "worker.heartbeat").write_text(str(time.time()))
            await asyncio.sleep(15)

    heart = asyncio.create_task(heartbeat())
    last_retention = 0.0
    try:
        while not stop.is_set():
            if time.monotonic() - last_retention > 60:
                try:
                    await asyncio.to_thread(sweep_retention, repository)
                except Exception as exc:
                    logger.error("Privacy maintenance failed type=%s", type(exc).__name__)
                last_retention = time.monotonic()
            for user_id, should_notify in await asyncio.to_thread(complete_deletions, repository):
                if should_notify:
                    try:
                        await bot.send_message(
                            int(user_id),
                            "Данные аккаунта удалены из сервиса и управляемых резервных копий: "
                            "конспекты, расшифровки, задания и история согласий. "
                            "Минимальная запись об уничтожении без содержимого материалов хранится 3 года. "
                            "Сообщения в Telegram и ранее переданные внешним сервисам данные "
                            "этой командой не удаляются. Чтобы начать заново, отправьте /start.",
                        )
                    except Exception:
                        logger.warning("Privacy completion notification unavailable")
            job = await asyncio.to_thread(repository.claim)
            if not job:
                try:
                    await asyncio.wait_for(stop.wait(), 2)
                except TimeoutError:
                    pass
                continue
            logger.info("Job started id=%s attempt=%s", job["id"], job["attempts"])
            try:
                await run_job_guarded(job, bot, repository)
            except ProcessingCancelled:
                await asyncio.to_thread(repository.finish, job, "PrivacyDeletion", terminal=True)
            except Exception as exc:
                # Never store provider response bodies, tokens or transcript contents in logs.
                error = type(exc).__name__
                logger.error("Job failed id=%s type=%s", job["id"], error)
                terminal = isinstance(exc, (SummaryUnavailable, LegalAcceptanceRequired))
                await asyncio.to_thread(repository.finish, job, error, terminal=terminal)
                if job["payload"].get("kind") not in {"translation", "transcript_translation"} and (
                    terminal or job["attempts"] >= 3
                ):
                    if isinstance(exc, LegalAcceptanceRequired):
                        failure_text = (
                            "Примите актуальные условия через /start и отправьте запись снова."
                        )
                    elif isinstance(exc, SummaryUnavailable):
                        failure_text = (
                            f"Не удалось создать конспект через OpenRouter. Код: {job['id'][:8]}"
                        )
                    else:
                        failure_text = f"Не удалось обработать запись. Повторите отправку. Код: {job['id'][:8]}"
                    try:
                        await bot.edit_message_text(
                            chat_id=job["payload"]["chat_id"],
                            message_id=job["payload"]["status_id"],
                            text=failure_text,
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
