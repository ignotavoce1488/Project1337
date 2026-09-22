"""Provider adapters: bounded HTTP retries, validated responses, remote-file cleanup."""

import asyncio
import json
import logging
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from slovech.core.config import get_settings
from slovech.core.models import Summary

logger = logging.getLogger(__name__)
BASE = "https://generativelanguage.googleapis.com"


class ProviderError(RuntimeError):
    pass


class QuotaExceeded(ProviderError):
    """Every configured Gemini key has returned a quota error."""


class KeyQuotaExceeded(ProviderError):
    """One Gemini key has returned HTTP 429."""


async def request(client, method, url, **kwargs):
    for attempt in range(3):
        try:
            response = await client.request(method, url, **kwargs)
        except httpx.TransportError:
            if attempt == 2:
                raise ProviderError("Provider transport unavailable") from None
        else:
            if response.is_success:
                return response
            if response.status_code == 429:
                raise KeyQuotaExceeded("Provider HTTP 429")
            if response.status_code not in {500, 502, 503, 504}:
                raise ProviderError(f"Provider HTTP {response.status_code}")
            if attempt == 2:
                raise ProviderError(f"Provider HTTP {response.status_code}")
        await asyncio.sleep(2**attempt)
    raise ProviderError("Provider unavailable")


def extract_text(data):
    candidates = data.get("candidates", [])
    if not candidates or candidates[0].get("finishReason") not in {None, "STOP"}:
        raise ProviderError("Provider returned incomplete or blocked content")
    text = "\n".join(
        part.get("text", "")
        for part in candidates[0].get("content", {}).get("parts", [])
        if not part.get("thought")
    ).strip()
    if not text:
        raise ProviderError("Provider returned empty content")
    return text


async def delete_remote(client, name, key):
    try:
        await request(client, "DELETE", f"{BASE}/v1beta/{name}", headers={"x-goog-api-key": key})
    except Exception:
        logger.warning("Remote audio cleanup failed; provider retention policy applies")


async def delete_interaction(client, interaction_id, key):
    try:
        await request(
            client,
            "DELETE",
            f"{BASE}/v1beta/interactions/{interaction_id}",
            headers={"x-goog-api-key": key},
        )
    except Exception:
        logger.warning("Transcription interaction cleanup failed; provider retention applies")


async def wait_for_interaction(client, data, key):
    interaction = data.get("interaction", data)
    interaction_id = interaction.get("id", "")
    if not interaction_id:
        raise ProviderError("Transcription interaction has no id")
    for _ in range(120):
        status = interaction.get("status")
        if status == "completed":
            return interaction
        if status == "incomplete" and any(
            content.get("text", "").strip()
            for step in interaction.get("steps", [])
            if step.get("type") == "model_output"
            for content in step.get("content", [])
            if content.get("type") == "text"
        ):
            return interaction
        if status not in {"queued", "in_progress"}:
            details = interaction.get("incomplete_details") or interaction.get("error")
            raise ProviderError(
                f"Transcription interaction ended with status {status}, details={details}"
            )
        await asyncio.sleep(5)
        response = await request(
            client,
            "GET",
            f"{BASE}/v1beta/interactions/{interaction_id}",
            headers={"x-goog-api-key": key},
            timeout=60,
        )
        interaction = response.json().get("interaction", response.json())
    raise ProviderError("Transcription interaction polling timeout")


async def upload_file_to_gemini(client, file_path, mime_type, api_key):
    path = Path(file_path)
    response = await request(
        client,
        "POST",
        f"{BASE}/upload/v1beta/files",
        headers={
            "x-goog-api-key": api_key,
            "X-Goog-Upload-Protocol": "resumable",
            "X-Goog-Upload-Command": "start",
            "X-Goog-Upload-Header-Content-Length": str(path.stat().st_size),
            "X-Goog-Upload-Header-Content-Type": mime_type,
        },
        json={"file": {"display_name": path.name}},
    )
    upload_url = response.headers.get("x-goog-upload-url", "")
    parsed = urlsplit(upload_url)
    if parsed.scheme != "https" or parsed.hostname != "generativelanguage.googleapis.com":
        raise ProviderError("Invalid provider upload URL")

    async def chunks():
        with path.open("rb") as stream:
            while chunk := await asyncio.to_thread(stream.read, 1024 * 1024):
                yield chunk

    # Streaming bodies cannot be replayed by the retry helper.
    response = await client.post(
        upload_url,
        headers={
            "Content-Length": str(path.stat().st_size),
            "X-Goog-Upload-Offset": "0",
            "X-Goog-Upload-Command": "upload, finalize",
        },
        content=chunks(),
        timeout=180,
    )
    if not response.is_success:
        if response.status_code == 429:
            raise KeyQuotaExceeded("Upload HTTP 429")
        raise ProviderError(f"Upload HTTP {response.status_code}")
    remote = response.json()["file"]
    name = remote["name"]
    try:
        # Long recordings can remain PROCESSING for several minutes after upload.
        # Keep this below the worker's overall job deadline while avoiding needless
        # re-uploads through every configured API key.
        for _ in range(300):
            if remote.get("state") == "ACTIVE":
                return remote["uri"], name
            if remote.get("state") == "FAILED":
                raise ProviderError("Remote audio processing failed")
            await asyncio.sleep(2)
            response = await request(
                client, "GET", f"{BASE}/v1beta/{name}", headers={"x-goog-api-key": api_key}
            )
            remote = response.json()
        raise ProviderError("Remote audio processing timeout")
    except BaseException:
        await delete_remote(client, name, api_key)
        raise


def extract_transcription(data: dict) -> str:
    interaction = data.get("interaction", data)
    if interaction.get("status") not in {"completed", "incomplete"}:
        raise ProviderError("Transcription interaction did not complete")
    text = "\n".join(
        content.get("text", "")
        for step in interaction.get("steps", [])
        if step.get("type") == "model_output"
        for content in step.get("content", [])
        if content.get("type") == "text"
    ).strip()
    if not text:
        raise ProviderError("Transcription interaction returned empty text")
    cyrillic = sum("а" <= char.lower() <= "я" or char.lower() == "ё" for char in text)
    latin = sum("a" <= char.lower() <= "z" for char in text)
    return f"[LANG:{'RU' if cyrillic >= latin else 'EN'}]\n{text}"


def get_summary_prompt(lang: str) -> str:
    if lang == "en":
        return (
            "Ты — профессиональный редактор. Твоя цель — сделать ИДЕАЛЬНО ЧИТАЕМЫЙ и красиво оформленный конспект на основе предоставленной расшифровки.\n"
            "Поскольку оригинальный текст на английском, тебе нужно вернуть JSON с двумя версиями конспекта: оригинальной (на английском) и переведенной (на русском).\n"
            "Сформируй ответ строго в формате JSON со следующими полями:\n"
            "{\n"
            '  "title": "Ёмкий заголовок (до 7 слов) на английском",\n'
            '  "summary": "Подробный конспект в формате Markdown (с подзаголовками ## и списками) на английском",\n'
            '  "key_points": ["Key point 1", "Key point 2", "Key point 3"],\n'
            '  "title_ru": "Заголовок на русском",\n'
            '  "summary_ru": "Подробный конспект в формате Markdown на русском",\n'
            '  "key_points_ru": ["Ключевой вывод 1", "Ключевой вывод 2", "Ключевой вывод 3"]\n'
            "}\n"
            "Отвечай ТОЛЬКО чистым JSON без обратных кавычек."
        )
    return (
        "Ты — профессиональный редактор. Твоя цель — сделать ИДЕАЛЬНО ЧИТАЕМЫЙ и красиво оформленный конспект на основе предоставленной расшифровки.\n"
        "Сформируй ответ строго в формате JSON со следующими полями:\n"
        "{\n"
        '  "title": "Ёмкий, информативный заголовок записи (до 7-10 слов)",\n'
        '  "summary": "Сверхподробный текст в формате Markdown (с подзаголовками ## и списками).",\n'
        '  "key_points": ["Ключевой вывод 1", "Ключевой вывод 2", "Ключевой вывод 3"]\n'
        "}\n"
        "Отвечай ТОЛЬКО чистым JSON без обратных кавычек."
    )


async def transcribe_audio_with_gemini(
    file_path: str, mime_type: str = "audio/mpeg", exhausted_keys: set[str] | None = None
) -> str:
    settings = get_settings()
    keys = list(dict.fromkeys(
        key.strip() for key in settings.gemini_api_keys.get_secret_value().split(",") if key.strip()
    ))
    exhausted = exhausted_keys if exhausted_keys is not None else set()
    if keys and all(key in exhausted for key in keys):
        raise QuotaExceeded("All Gemini transcription keys exceeded quota")
    async with httpx.AsyncClient(timeout=180, follow_redirects=False) as client:
        for key in (key for key in keys if key not in exhausted):
            name = None
            interaction_id = None
            try:
                uri, name = await upload_file_to_gemini(client, file_path, mime_type, key)
                response = await request(
                    client,
                    "POST",
                    f"{BASE}/v1beta/interactions",
                    headers={"x-goog-api-key": key},
                    json={
                        "model": "gemini-3.5-transcribe",
                        "input": [{"type": "audio", "uri": uri, "mime_type": mime_type}],
                        "generation_config": {
                            "transcription_config": {"mode": {"type": "verbatim"}}
                        },
                        "store": True,
                    },
                    timeout=600,
                )
                interaction = response.json().get("interaction", response.json())
                interaction_id = interaction.get("id")
                interaction = await wait_for_interaction(client, interaction, key)
                return extract_transcription(interaction)
            except KeyQuotaExceeded:
                exhausted.add(key)
                logger.warning("Gemini transcription quota exceeded key_index=%s", keys.index(key) + 1)
            except (ProviderError, httpx.HTTPError, ValueError, KeyError) as exc:
                logger.warning(
                    "Audio upload or transcription failed type=%s reason=%s",
                    type(exc).__name__,
                    str(exc),
                )
            finally:
                if interaction_id:
                    await delete_interaction(client, interaction_id, key)
                if name:
                    await delete_remote(client, name, key)
    if keys and all(key in exhausted for key in keys):
        raise QuotaExceeded("All Gemini transcription keys exceeded quota")
    raise ProviderError("Transcription providers unavailable")


def parse_summary(text: str) -> dict:
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return Summary.model_validate(json.loads(text)).model_dump()


async def generate_summary_with_openrouter(transcription: str, lang: str = "ru") -> dict:
    settings = get_settings()
    prompt = get_summary_prompt(lang)
    async with httpx.AsyncClient(timeout=120, follow_redirects=False) as client:
        if settings.openrouter_api_key.get_secret_value():
            for model in filter(None, settings.openrouter_models.split(",")):
                try:
                    response = await request(
                        client,
                        "POST",
                        "https://openrouter.ai/api/v1/chat/completions",
                        headers={
                            "Authorization": f"Bearer {settings.openrouter_api_key.get_secret_value()}"
                        },
                        json={
                            "model": model.strip(),
                            "messages": [
                                {"role": "system", "content": prompt},
                                {"role": "user", "content": transcription},
                            ],
                            "temperature": 0.3,
                        },
                    )
                    choice = response.json()["choices"][0]
                    if choice.get("finish_reason") != "stop":
                        raise ProviderError("Incomplete summary")
                    return parse_summary(choice["message"]["content"])
                except (ProviderError, ValueError, KeyError, IndexError):
                    logger.warning("Summary attempt failed")
        for key in filter(
            None, (k.strip() for k in settings.gemini_api_keys.get_secret_value().split(","))
        ):
            for model in settings.gemini_models.split(","):
                try:
                    response = await request(
                        client,
                        "POST",
                        f"{BASE}/v1beta/models/{model.strip()}:generateContent",
                        headers={"x-goog-api-key": key},
                        json={
                            "contents": [{"parts": [{"text": f"{prompt}\n\n{transcription}"}]}],
                            "generationConfig": {"responseMimeType": "application/json"},
                        },
                    )
                    return parse_summary(extract_text(response.json()))
                except (ProviderError, ValueError, KeyError, IndexError):
                    logger.warning("Summary fallback failed")
    raise ProviderError("Summary providers unavailable")
