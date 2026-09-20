"""One-container test stack: real bot, API, worker and temporary HTTPS tunnel."""

import asyncio
import contextlib
import json
import os
import re
import signal
import sys
import time
from pathlib import Path

import httpx
from aiogram import Bot
from aiogram.types import MenuButtonWebApp, WebAppInfo

from slovech.core.config import Settings
from slovech.core.runtime import process_lock

TUNNEL_URL = re.compile(r"https://[a-z0-9]+(?:-[a-z0-9]+)*\.trycloudflare\.com\b")


class StackError(RuntimeError):
    """A safe startup diagnostic that never contains external response bodies."""


def status_path():
    return Path(os.environ.get("DATA_DIR", "/data")) / "local-stack.json"


def child_environment(settings: Settings, domain: str) -> dict[str, str]:
    # Share the same settings with all three application processes.
    return {
        **os.environ,
        "ENVIRONMENT": "production",
        "DOMAIN": domain,
        "BOT_TOKEN": settings.bot_token.get_secret_value(),
        "GEMINI_API_KEYS": settings.gemini_api_keys.get_secret_value(),
        "GEMINI_MODELS": settings.gemini_models,
        "OPENROUTER_API_KEY": settings.openrouter_api_key.get_secret_value(),
        "OPENROUTER_MODELS": settings.openrouter_models,
        "DATA_DIR": str(settings.data_dir),
        "AUDIO_DIR": str(settings.audio_dir),
        "STATIC_DIR": str(settings.static_dir),
        "ADMIN_SECRET": "",
        "ADMIN_USER_ID": "0",
        "TELEGRAM_API_URL": "",
    }


async def read_tunnel(process, domain):
    while line := await process.stdout.readline():
        message = line.decode(errors="replace")
        match = TUNNEL_URL.search(message)
        if match and not domain.done():
            domain.set_result(match.group())
        # Only tunnel diagnostics, never application credentials.
        if "ERR" in message or "WRN" in message:
            print(f"[tunnel] {message.rstrip()}", flush=True)
    if not domain.done():
        domain.set_exception(StackError("HTTPS tunnel exited before receiving an address"))


async def wait_api(process, url="http://127.0.0.1:8000/ready"):
    async with httpx.AsyncClient(timeout=3, trust_env=False) as client:
        for _ in range(60):
            if process.returncode is not None:
                raise StackError("API exited during startup")
            try:
                response = await client.get(url)
                if response.status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            await asyncio.sleep(1)
    raise StackError("API readiness timed out")


async def supervise(settings):
    processes = []
    reader = None
    bot = Bot(token=settings.bot_token.get_secret_value())
    status_path().unlink(missing_ok=True)
    try:
        me = await bot.get_me()
        webhook = await bot.get_webhook_info()
        if webhook.url:
            raise StackError("This bot has a webhook. Use a separate test bot from BotFather.")
        print(f"Test bot: https://t.me/{me.username}", flush=True)
        print("Starting temporary HTTPS tunnel...", flush=True)
        tunnel = await asyncio.create_subprocess_exec(
            "cloudflared",
            "tunnel",
            "--no-autoupdate",
            "--protocol",
            "http2",
            "--url",
            "http://127.0.0.1:8000",
            "--metrics",
            "127.0.0.1:2000",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        processes.append(tunnel)
        domain = asyncio.get_running_loop().create_future()
        reader = asyncio.create_task(read_tunnel(tunnel, domain))
        public_url = await asyncio.wait_for(domain, 120)
        env = child_environment(settings, public_url)
        api = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "uvicorn",
            "slovech.server:app",
            "--host",
            "0.0.0.0",
            "--port",
            "8000",
            "--workers",
            "1",
            "--no-proxy-headers",
            "--no-access-log",
            env=env,
        )
        processes.append(api)
        await wait_api(api)
        for module in ("slovech.worker", "slovech.bot"):
            processes.append(
                await asyncio.create_subprocess_exec(sys.executable, "-m", module, env=env)
            )
        # A new tunnel URL is automatically applied on every container start.
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(
                text="Конспекты", web_app=WebAppInfo(url=f"{public_url}/app")
            )
        )
        status_path().write_text(
            json.dumps(
                {
                    "bot_url": f"https://t.me/{me.username}",
                    "miniapp_url": f"{public_url}/app",
                    "pids": [process.pid for process in processes],
                }
            )
        )
        print(
            f"READY: open https://t.me/{me.username}, send /start, then open Конспекты.", flush=True
        )
        print(f"Mini App: {public_url}/app | Local API: http://localhost:8000/ready", flush=True)
        waiters = [asyncio.create_task(process.wait()) for process in processes]
        try:
            await asyncio.wait(waiters, return_when=asyncio.FIRST_COMPLETED)
            raise StackError("A stack process exited; restarting the whole stack")
        finally:
            for waiter in waiters:
                waiter.cancel()
            await asyncio.gather(*waiters, return_exceptions=True)
    finally:
        status_path().unlink(missing_ok=True)
        for process in reversed(processes):
            if process.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    process.terminate()
        for process in reversed(processes):
            try:
                await asyncio.wait_for(process.wait(), 5)
            except TimeoutError:
                with contextlib.suppress(ProcessLookupError):
                    process.kill()
                await process.wait()
        if reader:
            reader.cancel()
            await asyncio.gather(reader, return_exceptions=True)
        await bot.session.close()


async def health():
    status = json.loads(status_path().read_text())
    for pid in status["pids"]:
        os.kill(pid, 0)
    heartbeat = status_path().parent / "worker.heartbeat"
    if time.time() - float(heartbeat.read_text()) > 60:
        raise RuntimeError("Worker heartbeat is stale")
    async with httpx.AsyncClient(timeout=3, trust_env=False) as client:
        for url in ("http://127.0.0.1:8000/ready", "http://127.0.0.1:2000/ready"):
            (await client.get(url)).raise_for_status()


async def main():
    settings = Settings(
        _env_file="/run/secrets/local.env",
        environment="development",
        domain="http://localhost:8000",
        admin_secret="",
        admin_user_id=0,
        telegram_api_url="",
        telegram_local_file_root=None,
    )
    settings.validate_worker()
    settings.prepare()
    with process_lock(settings.data_dir / "local-stack.lock"):
        task = asyncio.create_task(supervise(settings))
        for sig in (signal.SIGTERM, signal.SIGINT):
            asyncio.get_running_loop().add_signal_handler(sig, task.cancel)
        with contextlib.suppress(asyncio.CancelledError):
            await task


if __name__ == "__main__":
    try:
        asyncio.run(health() if "--health" in sys.argv else main())
    except StackError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        # Provider exceptions may contain tokens or response bodies.
        print(
            f"Test stack failed ({type(exc).__name__}). Check keys, network and test bot configuration.",
            file=sys.stderr,
        )
        sys.exit(1)
