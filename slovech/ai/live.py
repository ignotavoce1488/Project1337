"""Stream stored audio through Gemini Live transcription sessions."""

import asyncio
import base64
import json
import logging

import aiohttp

from slovech.ai.services import KeyQuotaExceeded, ProviderError, QuotaExceeded
from slovech.core.config import get_settings

logger = logging.getLogger(__name__)
LIVE_URL = (
    "wss://generativelanguage.googleapis.com/ws/"
    "google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent"
)
PCM_BYTES_PER_CHUNK = 3200  # 100 ms, 16-kHz mono, signed 16-bit little endian.


async def _transcribe_session(path: str, key: str) -> str:
    parts: list[str] = []
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=None)) as session:
        try:
            async with session.ws_connect(
                LIVE_URL,
                params={"key": key},
                heartbeat=30,
            ) as ws:
                await ws.send_json(
                    {
                        "setup": {
                            "model": "models/gemini-3.5-transcribe-live",
                            "generationConfig": {"responseModalities": ["TEXT"]},
                            "inputAudioTranscription": {"languageCodes": []},
                        }
                    }
                )
                setup = await ws.receive(timeout=30)
                if setup.type not in {aiohttp.WSMsgType.TEXT, aiohttp.WSMsgType.BINARY}:
                    raise ProviderError("Live transcription setup failed")
                try:
                    setup_data = json.loads(setup.data)
                except (ValueError, TypeError) as exc:
                    raise ProviderError("Invalid Live setup response") from exc
                if "setupComplete" not in setup_data:
                    raise ProviderError("Live transcription setup rejected")

                async def receive() -> None:
                    while True:
                        message = await ws.receive()
                        if message.type in {aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSE}:
                            raise ProviderError("Live transcription connection closed")
                        if message.type == aiohttp.WSMsgType.ERROR:
                            raise ProviderError("Live transcription connection failed")
                        if message.type not in {aiohttp.WSMsgType.TEXT, aiohttp.WSMsgType.BINARY}:
                            continue
                        try:
                            data = json.loads(message.data)
                        except (ValueError, TypeError) as exc:
                            raise ProviderError("Invalid Live transcription response") from exc
                        content = data.get("serverContent", {})
                        if (
                            transcript := content.get("inputTranscription", {})
                            .get("text", "")
                            .strip()
                        ):
                            parts.append(transcript)

                reader = asyncio.create_task(receive())
                proc = None
                try:
                    proc = await asyncio.create_subprocess_exec(
                        "ffmpeg",
                        "-nostdin",
                        "-v",
                        "error",
                        "-i",
                        path,
                        "-vn",
                        "-ac",
                        "1",
                        "-ar",
                        "16000",
                        "-f",
                        "s16le",
                        "pipe:1",
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.DEVNULL,
                    )
                    while chunk := await proc.stdout.read(PCM_BYTES_PER_CHUNK):
                        if reader.done():
                            await reader
                        await ws.send_json(
                            {
                                "realtimeInput": {
                                    "audio": {
                                        "data": base64.b64encode(chunk).decode("ascii"),
                                        "mimeType": "audio/pcm;rate=16000",
                                    }
                                }
                            }
                        )
                        await asyncio.sleep(len(chunk) / 32000)
                    if await proc.wait() != 0:
                        raise ProviderError("Audio conversion for Live transcription failed")
                    await ws.send_json({"realtimeInput": {"audioStreamEnd": True}})
                    await asyncio.sleep(5)
                    if reader.done():
                        await reader
                finally:
                    reader.cancel()
                    await asyncio.gather(reader, return_exceptions=True)
                    if proc and proc.returncode is None:
                        proc.kill()
                        await proc.wait()
        except aiohttp.WSServerHandshakeError as exc:
            if exc.status == 429:
                raise KeyQuotaExceeded("Live HTTP 429") from None
            raise ProviderError(f"Live handshake HTTP {exc.status}") from None
        except (aiohttp.ClientError, TimeoutError, OSError) as exc:
            raise ProviderError("Live transcription transport failed") from exc
    if not parts:
        raise ProviderError("Live transcription returned no speech")
    return " ".join(parts)


async def transcribe_audio_live(file_path: str, exhausted_keys: set[str] | None = None) -> str:
    settings = get_settings()
    keys = list(
        dict.fromkeys(
            key.strip()
            for key in settings.gemini_api_keys.get_secret_value().split(",")
            if key.strip()
        )
    )
    exhausted = exhausted_keys if exhausted_keys is not None else set()
    if keys and all(key in exhausted for key in keys):
        raise QuotaExceeded("All Gemini Live keys returned HTTP 429")
    for index, key in enumerate(keys, start=1):
        if key in exhausted:
            continue
        try:
            transcript = await _transcribe_session(file_path, key)
            cyrillic = sum("а" <= char.lower() <= "я" or char.lower() == "ё" for char in transcript)
            latin = sum("a" <= char.lower() <= "z" for char in transcript)
            language = "RU" if cyrillic >= latin else "EN"
            return f"[LANG:{language}]\n{transcript}"
        except KeyQuotaExceeded:
            exhausted.add(key)
            logger.warning("Gemini Live rate limit key_index=%s", index)
    if keys and all(key in exhausted for key in keys):
        raise QuotaExceeded("All Gemini Live keys returned HTTP 429")
    raise ProviderError("No Gemini Live keys configured")
