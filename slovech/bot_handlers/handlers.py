"""Thin Telegram transport: validate, enqueue and serve owner-scoped documents."""

import asyncio
import re
import uuid

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    WebAppInfo,
)

from slovech.core.config import SAFE_ID_REGEX, get_settings
from slovech.core.documents import render_docx
from slovech.core.storage import QueueFull, Repository
from slovech.core.youtube import youtube_video_id

router = Router()


def is_admin(user) -> bool:
    if not user:
        return False
    if getattr(user, "username", "") and user.username.lower() == "inwhtmst":
        return True
    return bool(get_settings().admin_user_id > 0 and user.id == get_settings().admin_user_id)


@router.message(CommandStart())
async def handle_start(message: Message):
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Открыть конспекты",
                    web_app=WebAppInfo(url=f"{get_settings().domain}/app?v=3"),
                )
            ]
        ]
    )
    await message.answer(
        "Отправьте аудио, голосовое сообщение или ссылку на YouTube. Конспект появится в вашем личном профиле.",
        reply_markup=keyboard,
    )


@router.message(Command("admin"))
async def handle_admin(message: Message, repository: Repository):
    if not is_admin(message.from_user):
        return

    def stats():
        with repository.connection() as db:
            jobs = dict(db.execute("SELECT state,COUNT(*) FROM jobs GROUP BY state").fetchall())
            total_lectures = db.execute("SELECT COUNT(*) FROM lectures").fetchone()[0]
            unique_users = db.execute("SELECT COUNT(DISTINCT user_id) FROM lectures").fetchone()[0]
            return jobs, total_lectures, unique_users

    jobs, total_lectures, unique_users = await asyncio.to_thread(stats)
    await message.answer(
        f"📊 <b>Статистика системы</b>\n\n"
        f"👥 Пользователей: {unique_users}\n"
        f"📚 Конспектов: {total_lectures}\n\n"
        f"⚙️ <b>Очередь задач</b>\n"
        f"В очереди: {jobs.get('pending', 0)}\n"
        f"В работе: {jobs.get('running', 0)}\n"
        f"Завершено: {jobs.get('done', 0)}\n"
        f"Ошибок: {jobs.get('failed', 0)}",
        parse_mode="HTML",
    )


async def enqueue(message: Message, repository: Repository, payload: dict):
    if not message.from_user or message.chat.type != "private":
        await message.answer("Обработка доступна в личном чате с ботом.")
        return
    status = await message.answer("⏳ Запись добавляется в очередь…")
    payload.update(chat_id=message.chat.id, status_id=status.message_id)
    try:
        created = await asyncio.to_thread(
            repository.enqueue,
            uuid.uuid4().hex,
            f"{message.chat.id}:{message.message_id}",
            str(message.from_user.id),
            payload,
        )
    except QueueFull:
        await status.edit_text(
            "Очередь заполнена. Дождитесь обработки предыдущих записей и повторите отправку."
        )
        return
    await status.edit_text(
        "⏳ Запись в очереди. Сообщу, когда конспект будет готов."
        if created
        else "Эта запись уже принята в обработку."
    )


@router.message(F.audio | F.voice | F.document)
async def handle_audio(message: Message, repository: Repository):
    media = message.voice or message.audio or message.document
    if not media:
        return
    if (
        message.document
        and not (media.mime_type or "").startswith("audio/")
        and not (media.file_name or "")
        .lower()
        .endswith((".mp3", ".m4a", ".wav", ".ogg", ".aac", ".flac"))
    ):
        await message.answer("Поддерживаются только аудиофайлы.")
        return
    if not media.file_size or media.file_size > get_settings().max_upload_bytes:
        await message.answer(
            f"Размер файла должен быть не более {get_settings().max_upload_bytes // (1024 * 1024)} МБ."
        )
        return
    await enqueue(message, repository, {"kind": "audio", "file_id": media.file_id})


@router.message(F.text)
async def handle_youtube_link(message: Message, repository: Repository):
    match = re.search(r"https?://\S+", message.text or "")
    try:
        video = youtube_video_id(match.group(0) if match else "")
    except ValueError:
        await message.answer("Отправьте аудио, голосовое сообщение или ссылку на видео YouTube.")
        return
    await enqueue(
        message,
        repository,
        {"kind": "youtube", "url": f"https://www.youtube.com/watch?v={video}", "video_id": video},
    )


@router.callback_query(F.data.startswith("dl_"))
async def handle_download_docx(query: CallbackQuery, bot: Bot, repository: Repository):
    parts = (query.data or "")[3:].split("_", 1)
    lang, lecture_id = (
        (parts[0], parts[1])
        if len(parts) == 2 and parts[0] in {"ru", "en"}
        else ("ru", (query.data or "")[3:])
    )
    lecture = (
        await asyncio.to_thread(repository.get, lecture_id, str(query.from_user.id))
        if SAFE_ID_REGEX.fullmatch(lecture_id)
        else None
    )
    if not lecture:
        await query.answer("Запись не найдена.", show_alert=True)
        return
    await query.answer("Готовлю документ…")
    body, name = await asyncio.to_thread(render_docx, lecture, lang)
    await bot.send_document(query.from_user.id, BufferedInputFile(body, filename=name))
