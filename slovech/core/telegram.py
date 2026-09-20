from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer

from slovech.core.config import Settings


def create_bot(settings: Settings) -> Bot:
    session = AiohttpSession(timeout=60)
    if settings.telegram_api_url:
        session = AiohttpSession(
            api=TelegramAPIServer.from_base(
                settings.telegram_api_url, is_local=settings.telegram_local_file_root is not None
            ),
            timeout=60,
        )
    return Bot(
        settings.bot_token.get_secret_value(),
        session=session,
        default=DefaultBotProperties(parse_mode="HTML"),
    )
