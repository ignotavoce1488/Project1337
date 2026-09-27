import asyncio
import logging

from aiogram import Dispatcher
from aiogram.types import BotCommand

from slovech.bot_handlers.handlers import router
from slovech.core.config import get_settings
from slovech.core.logging import configure_logging
from slovech.core.runtime import process_lock
from slovech.core.storage import Repository
from slovech.core.telegram import create_bot

logger = logging.getLogger(__name__)


async def register_bot_commands(bot):
    """Telegram's slash menu is configured separately from message handlers."""
    await bot.set_my_commands([
        BotCommand(command="start", description="Открыть бота"),
        BotCommand(command="language", description="Выбрать язык / Choose language"),
        BotCommand(command="privacy", description="Условия и конфиденциальность"),
        BotCommand(command="delete_me", description="Удалить мои данные"),
    ])


async def main():
    configure_logging()
    settings = get_settings()
    settings.validate_bot()
    repository = Repository(settings)
    repository.initialize()
    bot = create_bot(settings)
    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    try:
        # Persist each update before polling the next batch; no unbounded handler tasks.
        with process_lock(settings.data_dir / "bot.lock"):
            await register_bot_commands(bot)
            await dispatcher.start_polling(bot, repository=repository, handle_as_tasks=False)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
