from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import EditMessageText

from slovech.bot_handlers.handlers import handle_download_docx, is_admin
from slovech.core.runtime import process_lock
from slovech.worker import notify


async def test_callback_denies_other_owner(repo, lecture):
    repo.save(lecture)
    query = SimpleNamespace(
        data="dl_lecture1", from_user=SimpleNamespace(id=999), answer=AsyncMock()
    )
    bot = AsyncMock()
    await handle_download_docx(query, bot, repo)
    bot.send_document.assert_not_called()
    assert query.answer.await_args.kwargs["show_alert"]


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


async def test_notification_retry_is_idempotent(settings, lecture):
    bot = AsyncMock()
    bot.edit_message_text.side_effect = TelegramBadRequest(
        method=EditMessageText(text="test"), message="Bad Request: message is not modified"
    )
    await notify(bot, {"payload": {"chat_id": 123, "status_id": 456}}, lecture, settings)


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
