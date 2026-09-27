"""File-based speech recognition through AITUNNEL's OpenAI-compatible API."""

import logging
from pathlib import Path

import httpx

from slovech.ai.services import ProviderError
from slovech.core.config import get_settings
from slovech.core.languages import LANGUAGES

logger = logging.getLogger(__name__)
TRANSCRIPTION_URL = "https://api.aitunnel.ru/v1/audio/transcriptions"
MODEL = "whisper-large-v3-turbo"
FALLBACK_MODEL = "qwen3-asr-0.6b"
MAX_FILE_BYTES = 24_000_000  # Keep below the provider's 25 MB decimal limit.


class TranscriptionHTTPError(ProviderError):
    def __init__(self, status_code: int):
        self.status_code = status_code
        super().__init__(f"AITUNNEL transcription HTTP {status_code}")


async def transcribe_audio_with_aitunnel(
    file_path: str, model: str = MODEL, language_hint: str | None = None
) -> str:
    path = Path(file_path)
    if not path.is_file() or not 0 < path.stat().st_size < MAX_FILE_BYTES:
        raise ValueError("Transcription segment must be smaller than 24 MB")
    key = get_settings().aitunnel_api_key.get_secret_value()
    if not key:
        raise ProviderError("AITUNNEL transcription key is not configured")
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(600, connect=30)) as client:
            with path.open("rb") as audio:
                mime_type = "audio/ogg" if path.suffix.lower() == ".ogg" else "audio/mpeg"
                data = {"model": model}
                if language_hint in LANGUAGES:
                    data["language"] = language_hint
                response = await client.post(
                    TRANSCRIPTION_URL,
                    headers={"Authorization": f"Bearer {key}"},
                    data=data,
                    files={"file": (path.name, audio, mime_type)},
                )
    except httpx.HTTPError as exc:
        raise ProviderError("AITUNNEL transcription transport failed") from exc
    if not response.is_success:
        logger.warning("AITUNNEL transcription HTTP %s model=%s", response.status_code, model)
        raise TranscriptionHTTPError(response.status_code)
    try:
        transcript = response.json()["text"].strip()
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise ProviderError("AITUNNEL transcription response is invalid") from exc
    if not transcript:
        raise ProviderError("AITUNNEL transcription returned no speech")
    if language_hint:
        language = language_hint
    elif any("\u0600" <= char <= "\u06ff" for char in transcript):
        language = "ar"
    elif any("\u0900" <= char <= "\u097f" for char in transcript):
        language = "hi"
    else:
        cyrillic = sum("а" <= char.lower() <= "я" or char.lower() == "ё" for char in transcript)
        latin = sum("a" <= char.lower() <= "z" for char in transcript)
        language = "ru" if cyrillic >= latin else "en"
    return f"[LANG:{language.upper()}]\n{transcript}"
