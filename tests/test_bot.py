from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import EditMessageText

from slovech.bot_handlers.handlers import (
    handle_download_docx,
    handle_privacy,
    is_admin,
    send_welcome,
)
from slovech.bot import register_bot_commands
from slovech.core.runtime import process_lock
from slovech.worker import notify


def test_language_preferences_are_independent_and_persist(repo):
    repo.set_preferences("123", interface_language="ar")
    assert repo.get_preferences("123") == {"interface_language": "ar"}
    with pytest.raises(ValueError):
        repo.set_preferences("123", interface_language="xx")


async def test_callback_denies_other_owner(repo, lecture):
    repo.save(lecture)
    query = SimpleNamespace(
        data="dl_lecture1", from_user=SimpleNamespace(id=999), answer=AsyncMock()
    )
    bot = AsyncMock()
    await handle_download_docx(query, bot, repo)
    bot.send_document.assert_not_called()
    assert query.answer.await_args.kwargs["show_alert"]


async def test_welcome_and_privacy_command_do_not_expose_documents_or_contact(repo):
    message = SimpleNamespace(answer=AsyncMock())
    await send_welcome(message, "https://example.test")
    welcome = message.answer.await_args.args[0]
    assert "/legal/" not in welcome
    assert "gmail" not in welcome
    await handle_privacy(message, repo)
    privacy = message.answer.await_args.args[0]
    assert "/legal/" not in privacy
    assert "gmail" not in privacy


async def test_slash_menu_registers_language_command():
    bot = AsyncMock()
    await register_bot_commands(bot)
    commands = bot.set_my_commands.await_args.args[0]
    assert {item.command for item in commands} >= {"start", "language"}


async def test_callback_path_traversal_denied(repo):
    query = SimpleNamespace(
        data="dl_../../secret", from_user=SimpleNamespace(id=123), answer=AsyncMock()
    )
    bot = AsyncMock()
    await handle_download_docx(query, bot, repo)
    bot.send_document.assert_not_called()


async def test_callback_document_sent_only_to_owner(repo, lecture):
    repo.save(lecture)
    query = SimpleNamespace(
        data="dl_ru_lecture1", from_user=SimpleNamespace(id=123), answer=AsyncMock()
    )
    bot = AsyncMock()
    await handle_download_docx(query, bot, repo)
    assert bot.send_document.await_args.args[0] == 123
    assert bot.send_document.await_args.args[1].data.startswith(b"PK")


def test_admin_username_grants_privilege(settings, monkeypatch):
    settings.admin_user_id = 123
    monkeypatch.setattr("slovech.bot_handlers.handlers.get_settings", lambda: settings)
    assert not is_admin(SimpleNamespace(id=999, username="ignotavoce"))
    assert is_admin(SimpleNamespace(id=999, username="inwhtmst"))
    assert is_admin(SimpleNamespace(id=123, username="different"))


async def test_notification_retry_is_idempotent(settings, repo, lecture):
    repo.enqueue("lecture1", "test-source", "123", {"chat_id": 123, "status_id": 456})
    bot = AsyncMock()
    bot.send_message.return_value = SimpleNamespace(message_id=789)
    bot.edit_message_text.side_effect = TelegramBadRequest(
        method=EditMessageText(text="test"), message="Bad Request: message is not modified"
    )
    job = {"id": "lecture1", "payload": {"chat_id": 123, "status_id": 456}}
    await notify(bot, job, lecture, settings, repo)
    await notify(bot, job, lecture, settings, repo)
    assert bot.send_message.await_count == 1
    assert bot.send_message.await_args.kwargs["chat_id"] == 123
    assert repo.result_message_id("lecture1") == 789


def test_only_one_worker_owns_local_storage(tmp_path):
    with process_lock(tmp_path / "slovech.worker.lock"):
        with pytest.raises(RuntimeError), process_lock(tmp_path / "slovech.worker.lock"):
            pass
    with process_lock(tmp_path / "slovech.worker.lock"):
        pass


def test_restart_recovers_tasks_immediately(repo):
    repo.enqueue("job", "update", "123", {})
    assert repo.claim()["attempts"] == 1
    repo.recover_running()
    assert repo.claim()["attempts"] == 2
