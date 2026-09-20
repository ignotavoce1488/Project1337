import asyncio
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from scripts import local_stack


def test_application_processes_share_public_domain_and_keys(settings):
    env = local_stack.child_environment(settings, "https://test-name.trycloudflare.com")
    assert env["DOMAIN"] == "https://test-name.trycloudflare.com"
    assert env["ENVIRONMENT"] == "production"
    assert env["BOT_TOKEN"] == settings.bot_token.get_secret_value()
    assert env["ADMIN_SECRET"] == ""
    assert env["TELEGRAM_API_URL"] == ""


async def test_tunnel_reader_extracts_generated_url_and_reports_early_exit():
    stream = asyncio.StreamReader()
    stream.feed_data(b"INF Visit https://developers.cloudflare.com for help\n")
    stream.feed_data(b"INF | https://test-123.trycloudflare.com |\n")
    stream.feed_eof()
    domain = asyncio.get_running_loop().create_future()
    await local_stack.read_tunnel(SimpleNamespace(stdout=stream), domain)
    assert await domain == "https://test-123.trycloudflare.com"

    empty = asyncio.StreamReader()
    empty.feed_eof()
    domain = asyncio.get_running_loop().create_future()
    await local_stack.read_tunnel(SimpleNamespace(stdout=empty), domain)
    with pytest.raises(local_stack.StackError, match="HTTPS tunnel exited"):
        await domain


async def test_existing_webhook_is_not_deleted(settings, tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    bot = AsyncMock()
    bot.get_webhook_info.return_value = SimpleNamespace(url="https://existing.example/webhook")
    monkeypatch.setattr(local_stack, "Bot", lambda **kwargs: bot)
    spawn = AsyncMock()
    monkeypatch.setattr(local_stack.asyncio, "create_subprocess_exec", spawn)
    with pytest.raises(local_stack.StackError, match="separate test bot"):
        await local_stack.supervise(settings)
    bot.delete_webhook.assert_not_called()
    bot.set_chat_menu_button.assert_not_called()
    spawn.assert_not_called()
    bot.session.close.assert_awaited_once()


async def test_stack_updates_menu_and_stops_all_children_on_exit(settings, tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    bot = AsyncMock()
    bot.get_me.return_value = SimpleNamespace(username="slovech_test_bot")
    bot.get_webhook_info.return_value = SimpleNamespace(url="")
    monkeypatch.setattr(local_stack, "Bot", lambda **kwargs: bot)
    monkeypatch.setattr(local_stack, "wait_api", AsyncMock())
    children, calls = [], []

    class Child:
        def __init__(self, pid):
            self.pid = pid
            self.returncode = None
            self.stopped = asyncio.Event()
            self.stdout = asyncio.StreamReader()

        async def wait(self):
            await self.stopped.wait()
            return self.returncode

        def terminate(self):
            self.returncode = 0
            self.stopped.set()

    async def spawn(*args, **kwargs):
        calls.append((args, kwargs))
        child = Child(100 + len(children))
        children.append(child)
        if args[0] == "cloudflared":
            child.stdout.feed_data(b"https://local-test.trycloudflare.com\n")
        return child

    monkeypatch.setattr(local_stack.asyncio, "create_subprocess_exec", spawn)
    task = asyncio.create_task(local_stack.supervise(settings))
    try:
        async with asyncio.timeout(3):
            while not local_stack.status_path().exists():
                await asyncio.sleep(0.01)
        status = json.loads(local_stack.status_path().read_text())
        assert len(children) == 4
        assert status["bot_url"] == "https://t.me/slovech_test_bot"
        assert bot.set_chat_menu_button.call_args.kwargs["menu_button"].web_app.url == (
            "https://local-test.trycloudflare.com/app"
        )
        for _, kwargs in calls[1:]:
            assert kwargs["env"]["DOMAIN"] == "https://local-test.trycloudflare.com"
        children[-1].terminate()
        with pytest.raises(local_stack.StackError, match="process exited"):
            await task
        assert all(child.returncode is not None for child in children)
        assert not local_stack.status_path().exists()
        bot.session.close.assert_awaited_once()
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_health_rejects_stalled_worker(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    local_stack.status_path().write_text(json.dumps({"pids": []}))
    (tmp_path / "worker.heartbeat").write_text(str(time.time() - 120))
    with pytest.raises(RuntimeError, match="stale"):
        await local_stack.health()
