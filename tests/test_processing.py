import sys
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import SecretStr

from slovech.ai.aitunnel import (
    FALLBACK_MODEL,
    MAX_FILE_BYTES,
    MODEL,
    TranscriptionHTTPError,
    transcribe_audio_with_aitunnel,
)
from slovech.ai.live import transcribe_audio_live
from slovech.ai.services import (
    KeyQuotaExceeded,
    ProviderError,
    QuotaExceeded,
    SummaryUnavailable,
    extract_text,
    extract_transcription,
    generate_formatted_transcription_with_openrouter,
    generate_summary_with_openrouter,
    get_summary_prompt,
    parse_summary,
    request,
    transcribe_audio_with_gemini,
    upload_file_to_gemini,
)
from slovech.core.process import run_process
from slovech.core.youtube import youtube_video_id
from slovech.worker import (
    BoundedDownload,
    process_job,
    transcribe_audio,
)


async def test_translation_keeps_original_and_detects_source(monkeypatch, settings):
    import json

    from slovech.ai.services import translate_summary_with_openrouter

    settings.openrouter_api_key = SecretStr("test-key")
    settings.openrouter_models = "model-one"
    monkeypatch.setattr("slovech.ai.services.get_settings", lambda: settings)
    calls = []

    def respond(request):
        payload = json.loads(request.content)
        calls.append(payload)
        if payload["max_tokens"] == 700:
            content = json.dumps({"source_language": "en", "title": "Título",
                                  "key_points": ["Punto"]})
        else:
            content = "## Notas\nUn hecho concreto."
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop",
                                                       "message": {"content": content}}]})

    original_client = httpx.AsyncClient
    monkeypatch.setattr("slovech.ai.services.httpx.AsyncClient",
                        lambda **kwargs: original_client(transport=httpx.MockTransport(respond), **kwargs))
    original = {"title": "Title", "summary": "## Notes\nA concrete fact.",
                "key_points": ["Point"]}
    translated = await translate_summary_with_openrouter(original, "es")
    assert original["title"] == "Title"
    assert translated["source_language"] == "en"
    assert translated["translation_language"] == "es"
    assert translated["summary_translated"].startswith("## Notas")
    assert len(calls) == 2


async def test_transcript_translation_uses_separate_model_request(monkeypatch, settings):
    import json

    from slovech.ai.services import translate_transcription_chunk_with_openrouter

    settings.openrouter_api_key = SecretStr("test-key")
    settings.openrouter_models = "nvidia/nemotron-test"
    settings.transcript_translation_models = "nvidia/nemotron-test"
    monkeypatch.setattr("slovech.ai.services.get_settings", lambda: settings)
    requests = []

    def respond(request):
        payload = json.loads(request.content)
        requests.append(payload)
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop",
            "message": {"content": "Der Dozent erklärt die Quantenphysik."}}]})

    original_client = httpx.AsyncClient
    monkeypatch.setattr("slovech.ai.services.httpx.AsyncClient",
                    lambda **kwargs: original_client(transport=httpx.MockTransport(respond), **kwargs))
    result = await translate_transcription_chunk_with_openrouter(
        "Преподаватель объясняет квантовую физику.", "de"
    )
    assert result == "Der Dozent erklärt die Quantenphysik."
    assert len(requests) == 1
    assert requests[0]["max_tokens"] == 6144
    assert requests[0]["reasoning"] == {"enabled": False}
    assert requests[0]["messages"][1]["content"] == "Преподаватель объясняет квантовую физику."


async def test_transcript_translation_falls_back_when_light_model_fails(monkeypatch, settings):
    import json

    from slovech.ai.services import translate_transcription_chunk_with_openrouter

    settings.openrouter_api_key = SecretStr("test-key")
    settings.transcript_translation_models = "nvidia/nemotron-3.5-lightning:free"
    settings.openrouter_models = "liquid/fallback-test"
    monkeypatch.setattr("slovech.ai.services.get_settings", lambda: settings)
    attempted = []

    def respond(request):
        model = json.loads(request.content)["model"]
        attempted.append(model)
        if model == settings.transcript_translation_models:
            return httpx.Response(200, json={"error": {"message": "provider unavailable"}})
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop",
            "message": {"content": "Die Vorlesung beginnt."}}]})

    original_client = httpx.AsyncClient
    monkeypatch.setattr("slovech.ai.services.httpx.AsyncClient",
                    lambda **kwargs: original_client(transport=httpx.MockTransport(respond), **kwargs))
    assert await translate_transcription_chunk_with_openrouter("Лекция начинается.", "de") == "Die Vorlesung beginnt."
    assert attempted == [settings.transcript_translation_models, settings.openrouter_models]


async def process_queued_job(job, bot, repo):
    repo.enqueue(job["id"], job["id"], job["user_id"], job["payload"])
    with repo.connection() as db:
        db.execute("UPDATE jobs SET attempts=? WHERE id=?", (job.get("attempts", 1) - 1, job["id"]))
    await process_job(repo.claim(), bot, repo)


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.test/watch?v=abcdefghijk",
        "https://youtube.com.evil.test/watch?v=abcdefghijk",
        "file:///etc/passwd",
        "https://youtube.com@127.0.0.1/watch?v=abcdefghijk",
        "https://youtube.com/playlist?list=abcdef",
        "https://youtu.be/../secret",
        "https://youtube.com:123/watch?v=abcdefghijk",
    ],
)
def test_youtube_rejects_untrusted_urls(url):
    with pytest.raises(ValueError):
        youtube_video_id(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://youtu.be/abcdefghijk",
        "https://www.youtube.com/watch?v=abcdefghijk&list=123",
        "https://youtube.com/shorts/abcdefghijk",
    ],
)
def test_youtube_canonical_video(url):
    assert youtube_video_id(url) == "abcdefghijk"


def test_summary_and_incomplete_response_rejected():
    with pytest.raises(ValueError):
        parse_summary('{"title": [], "summary": "text"}')
    assert parse_summary('```json\n{"title":"T","summary":"S"}\n```')["title"] == "T"
    with pytest.raises(ProviderError):
        extract_text({"candidates": [{"finishReason": "MAX_TOKENS"}]})


def test_dedicated_transcription_response_and_language_detection():
    response = {
        "status": "completed",
        "steps": [{"type": "model_output", "content": [{"type": "text", "text": "Привет, мир"}]}],
    }
    assert extract_transcription(response) == "[LANG:RU]\nПривет, мир"
    with pytest.raises(ProviderError):
        extract_transcription({"status": "incomplete", "steps": []})


async def test_provider_retries_only_transient_failures(monkeypatch):
    monkeypatch.setattr("slovech.ai.services.asyncio.sleep", AsyncMock())
    calls = []

    def responder(req):
        calls.append(req)
        return httpx.Response(503 if len(calls) < 3 else 200, json={})

    async with httpx.AsyncClient(transport=httpx.MockTransport(responder)) as client:
        assert (await request(client, "GET", "https://provider.test")).status_code == 200
    assert len(calls) == 3
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(401))
    ) as client:
        with pytest.raises(ProviderError, match="401"):
            await request(client, "GET", "https://provider.test")
    quota_calls = []

    def quota_responder(req):
        quota_calls.append(req)
        return httpx.Response(429)

    async with httpx.AsyncClient(transport=httpx.MockTransport(quota_responder)) as client:
        with pytest.raises(KeyQuotaExceeded):
            await request(client, "GET", "https://provider.test")
    assert len(quota_calls) == 1


async def test_transcription_switches_keys_and_stops_when_all_exhausted(
    tmp_path, monkeypatch, settings
):
    audio = tmp_path / "audio.mp3"
    audio.write_bytes(b"audio")
    settings.gemini_api_keys = SecretStr("first,second,third")
    monkeypatch.setattr("slovech.ai.services.get_settings", lambda: settings)
    tried = []

    async def upload(client, path, mime, key):
        tried.append(key)
        if key in {"first", "second"}:
            raise KeyQuotaExceeded("Provider HTTP 429")
        return "uri", "files/test"

    class Response:
        def json(self):
            return {
                "id": "interaction",
                "status": "completed",
                "steps": [
                    {"type": "model_output", "content": [{"type": "text", "text": "Привет"}]}
                ],
            }

    monkeypatch.setattr("slovech.ai.services.upload_file_to_gemini", upload)
    monkeypatch.setattr("slovech.ai.services.request", AsyncMock(return_value=Response()))
    exhausted = set()
    assert (
        await transcribe_audio_with_gemini(str(audio), exhausted_keys=exhausted)
        == "[LANG:RU]\nПривет"
    )
    assert tried == ["first", "second", "third"]
    assert exhausted == {"first", "second"}

    async def all_quota(client, path, mime, key):
        tried.append(key)
        raise KeyQuotaExceeded("Provider HTTP 429")

    monkeypatch.setattr("slovech.ai.services.upload_file_to_gemini", all_quota)
    with pytest.raises(QuotaExceeded):
        await transcribe_audio_with_gemini(str(audio), exhausted_keys=exhausted)
    assert tried[-1] == "third"
    with pytest.raises(QuotaExceeded):
        await transcribe_audio_with_gemini(str(audio), exhausted_keys=exhausted)
    assert tried.count("third") == 2


async def test_live_transcription_rotates_keys_on_429(monkeypatch, settings):
    settings.gemini_api_keys = SecretStr("first,second")
    monkeypatch.setattr("slovech.ai.live.get_settings", lambda: settings)
    attempted = []

    async def live(path, key):
        attempted.append(key)
        if key == "first":
            raise KeyQuotaExceeded("Live HTTP 429")
        return "Привет, мир"

    monkeypatch.setattr("slovech.ai.live._transcribe_session", live)
    exhausted = set()
    assert await transcribe_audio_live("audio.mp3", exhausted) == "[LANG:RU]\nПривет, мир"
    assert attempted == ["first", "second"]
    assert exhausted == {"first"}


async def test_remote_failed_upload_deleted(monkeypatch, tmp_path):
    monkeypatch.setattr("slovech.ai.services.asyncio.sleep", AsyncMock())
    audio = tmp_path / "audio.mp3"
    audio.write_bytes(b"audio")
    calls = []

    def responder(req):
        calls.append((req.method, str(req.url)))
        if req.method == "DELETE":
            return httpx.Response(200, json={})
        if "/upload/v1beta/" in str(req.url):
            return httpx.Response(
                200,
                headers={
                    "x-goog-upload-url": "https://generativelanguage.googleapis.com/resumable"
                },
            )
        return httpx.Response(
            200, json={"file": {"name": "files/test", "state": "FAILED", "uri": "test"}}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(responder)) as client:
        with pytest.raises(ProviderError, match="failed"):
            await upload_file_to_gemini(client, audio, "audio/mpeg", "secret")
    assert calls[-1][0] == "DELETE"
    assert all("secret" not in url for _, url in calls)


async def test_subprocess_deadline():
    with pytest.raises(TimeoutError):
        await run_process(sys.executable, "-c", "import time; time.sleep(20)", timeout=0.05)


def test_download_actual_size_limit(tmp_path):
    stream = BoundedDownload(tmp_path / "audio", 4)
    try:
        stream.write(b"abcd")
        with pytest.raises(ValueError):
            stream.write(b"e")
    finally:
        stream.close()
    assert (tmp_path / "audio").stat().st_size == 4


async def test_aitunnel_uses_multipart_and_redacts_provider_errors(tmp_path, monkeypatch, settings):
    audio = tmp_path / "speech.mp3"
    audio.write_bytes(b"audio bytes")
    settings.aitunnel_api_key = SecretStr("test-key")
    monkeypatch.setattr("slovech.ai.aitunnel.get_settings", lambda: settings)
    requests = []

    def respond(req):
        requests.append(req)
        assert str(req.url) == "https://api.aitunnel.ru/v1/audio/transcriptions"
        assert req.headers["authorization"] == "Bearer test-key"
        assert b"whisper-large-v3-turbo" in req.content
        assert b"audio bytes" in req.content
        return httpx.Response(200, json={"text": "Привет, мир"})

    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        "slovech.ai.aitunnel.httpx.AsyncClient",
        lambda **kwargs: original_client(transport=httpx.MockTransport(respond), **kwargs),
    )
    assert await transcribe_audio_with_aitunnel(str(audio), language_hint="ru") == "[LANG:RU]\nПривет, мир"
    assert len(requests) == 1
    assert b'name="language"' in requests[0].content
    assert b"\r\nru\r\n" in requests[0].content


async def test_long_audio_is_transcribed_in_chunks(tmp_path, monkeypatch):
    audio = tmp_path / "audio.mp3"
    with audio.open("wb") as stream:
        stream.truncate(MAX_FILE_BYTES)

    async def split(*args, **kwargs):
        (tmp_path / "audio_part_000.mp3").write_bytes(b"a" * 8192)
        (tmp_path / "audio_part_001.mp3").write_bytes(b"b" * 8192)

    transcribe = AsyncMock(side_effect=["[LANG:RU]\nПервая", "[LANG:RU]\nВторая"])
    monkeypatch.setattr("slovech.worker.run_process", split)
    monkeypatch.setattr("slovech.worker.transcribe_audio_with_aitunnel", transcribe)
    assert await transcribe_audio(audio, 4000) == "[LANG:RU]\nПервая\n\nВторая"
    assert transcribe.await_count == 2
    assert not list(tmp_path.glob("audio_part_*.mp3"))


async def test_one_english_chunk_does_not_relabel_russian_recording(tmp_path, monkeypatch):
    audio = tmp_path / "audio.mp3"
    audio.write_bytes(b"audio")

    async def split(*args, **kwargs):
        for index in range(3):
            (tmp_path / f"audio_part_{index:03d}.mp3").write_bytes(b"a" * 8192)

    transcribe = AsyncMock(
        side_effect=[
            "[LANG:RU]\n" + "Русская речь. " * 12,
            "[LANG:EN]\nWrong English text.",
            "[LANG:RU]\n" + "Продолжение речи. " * 12,
        ]
    )
    monkeypatch.setattr("slovech.worker.run_process", split)
    monkeypatch.setattr("slovech.worker.transcribe_audio_with_aitunnel", transcribe)

    result = await transcribe_audio(audio, 1800, language_hint="ru")
    assert result.startswith("[LANG:RU]\n")
    assert transcribe.await_count == 3
    assert all(call.kwargs["language_hint"] == "ru" for call in transcribe.await_args_list)


async def test_short_audio_uses_aitunnel_without_chunking(tmp_path, monkeypatch):
    audio = tmp_path / "audio.mp3"
    audio.write_bytes(b"audio")
    transcribe = AsyncMock(return_value="[LANG:RU]\nРечь")
    split = AsyncMock()
    monkeypatch.setattr("slovech.worker.run_process", split)
    monkeypatch.setattr("slovech.worker.transcribe_audio_with_aitunnel", transcribe)
    assert await transcribe_audio(audio, 60) == "[LANG:RU]\nРечь"
    transcribe.assert_awaited_once_with(str(audio), model=MODEL, language_hint=None)
    split.assert_not_awaited()


async def test_short_audio_retry_reuses_paid_transcription(repo, monkeypatch):
    repo.enqueue("job", "source", "123", {})
    repo.claim()
    audio = repo.settings.audio_dir / "audio.mp3"
    audio.write_bytes(b"audio")
    transcribe = AsyncMock(return_value="[LANG:RU]\nСохранённая речь")
    monkeypatch.setattr("slovech.worker.transcribe_audio_with_aitunnel", transcribe)

    assert await transcribe_audio(audio, 60, "job", repo) == "[LANG:RU]\nСохранённая речь"
    assert await transcribe_audio(audio, 60, "job", repo) == "[LANG:RU]\nСохранённая речь"
    transcribe.assert_awaited_once()


async def test_forty_minute_audio_under_limit_is_split_by_duration(tmp_path, monkeypatch):
    audio = tmp_path / "audio.mp3"
    audio.write_bytes(b"audio")

    async def split(*args, **kwargs):
        assert "segment" in args
        for index in range(5):
            (tmp_path / f"audio_part_{index:03d}.mp3").write_bytes(b"a" * 8192)

    transcribe = AsyncMock(return_value="[LANG:RU]\nЧасть")
    monkeypatch.setattr("slovech.worker.run_process", split)
    monkeypatch.setattr("slovech.worker.transcribe_audio_with_aitunnel", transcribe)

    result = await transcribe_audio(audio, 40 * 60)
    assert result == "[LANG:RU]\n" + "\n\n".join(["Часть"] * 5)
    assert transcribe.await_count == 5
    assert not list(tmp_path.glob("audio_part_*.mp3"))


async def test_oversize_audio_is_split_without_whole_file_upload(tmp_path, monkeypatch):
    audio = tmp_path / "audio.mp3"
    with audio.open("wb") as stream:
        stream.truncate(MAX_FILE_BYTES)

    async def split(*args, **kwargs):
        assert "segment" in args
        (tmp_path / "audio_part_000.mp3").write_bytes(b"segment")

    transcribe = AsyncMock(return_value="[LANG:RU]\nРечь")
    monkeypatch.setattr("slovech.worker.run_process", split)
    monkeypatch.setattr("slovech.worker.transcribe_audio_with_aitunnel", transcribe)
    assert await transcribe_audio(audio, 7200) == "[LANG:RU]\nРечь"
    transcribe.assert_awaited_once_with(
        str(tmp_path / "audio_part_000.mp3"), model=MODEL, language_hint=None
    )
    assert not list(tmp_path.glob("audio_part_*.mp3"))


async def test_tiny_trailing_segment_is_not_sent_to_aitunnel(tmp_path, monkeypatch):
    audio = tmp_path / "audio.mp3"
    with audio.open("wb") as stream:
        stream.truncate(MAX_FILE_BYTES)

    async def convert(*args, **kwargs):
        if args[0] == "ffmpeg":
            (tmp_path / "audio_part_000.mp3").write_bytes(b"x" * 8192)
            (tmp_path / "audio_part_001.mp3").write_bytes(b"tiny")
        else:
            assert args[0] == "ffprobe"
            return b'{"format":{"duration":"0.096"}}'

    transcribe = AsyncMock(return_value="[LANG:RU]\nРечь")
    monkeypatch.setattr("slovech.worker.run_process", convert)
    monkeypatch.setattr("slovech.worker.transcribe_audio_with_aitunnel", transcribe)
    assert await transcribe_audio(audio, 600.096) == "[LANG:RU]\nРечь"
    transcribe.assert_awaited_once()
    assert not list(tmp_path.glob("audio_part_*.mp3"))


async def test_transcription_uses_fallback_after_provider_rate_limit(tmp_path, monkeypatch):
    audio = tmp_path / "audio.mp3"
    audio.write_bytes(b"audio")
    calls = []

    async def transcribe(path, model, language_hint=None):
        calls.append((path, model))
        if model == MODEL:
            raise TranscriptionHTTPError(429)
        return "[LANG:RU]\nРечь"

    monkeypatch.setattr("slovech.worker.transcribe_audio_with_aitunnel", transcribe)
    assert await transcribe_audio(audio, 60) == "[LANG:RU]\nРечь"
    assert [model for _, model in calls] == [MODEL, FALLBACK_MODEL]
    assert FALLBACK_MODEL == "qwen3-asr-0.6b"


async def test_completed_parts_survive_retry_without_paid_retranscription(repo, monkeypatch):
    repo.enqueue("job", "job", "123", {})
    repo.claim()
    audio = repo.settings.audio_dir / "audio.mp3"
    audio.write_bytes(b"audio")
    split_calls = 0
    calls = []

    async def split(*_args, **_kwargs):
        nonlocal split_calls
        split_calls += 1
        for index in range(2):
            (audio.parent / f"audio_part_{index:03d}.mp3").write_bytes(b"a" * 8192)

    async def transcribe(path, model, language_hint=None):
        calls.append((path, model))
        if path.endswith("part_000.mp3"):
            return "[LANG:RU]\nПервая"
        if len([call for call in calls if call[0].endswith("part_001.mp3")]) <= 2:
            raise ProviderError("temporary failure")
        return "[LANG:RU]\nВторая"

    monkeypatch.setattr("slovech.worker.run_process", split)
    monkeypatch.setattr("slovech.worker.transcribe_audio_with_aitunnel", transcribe)
    with pytest.raises(ProviderError):
        await transcribe_audio(audio, 900, "job", repo)
    assert repo.get_transcription_part("job", 0) == "[LANG:RU]\nПервая"
    assert repo.get_transcription_part("job", 1) is None
    assert not list(audio.parent.glob("audio_part_*.mp3"))

    assert await transcribe_audio(audio, 900, "job", repo) == "[LANG:RU]\nПервая\n\nВторая"
    assert len([call for call in calls if call[0].endswith("part_000.mp3")]) == 1
    assert split_calls == 2
    assert repo.get_transcription_part("job", 1) == "[LANG:RU]\nВторая"


async def test_openrouter_only_summarizes_and_falls_back_between_models(monkeypatch, settings):
    settings.openrouter_api_key = SecretStr("test-key")
    settings.openrouter_models = (
        "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free,liquid/lfm-2.5-2.6b:free"
    )
    monkeypatch.setattr("slovech.ai.services.get_settings", lambda: settings)
    calls = []

    def respond(req):
        assert str(req.url) == "https://openrouter.ai/api/v1/chat/completions"
        assert req.headers["authorization"] == "Bearer test-key"
        calls.append(req)
        if len(calls) == 1:
            return httpx.Response(429)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": '{"title":"Тест","summary":"Готово","key_points":[]}'
                        },
                    }
                ]
            },
        )

    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        "slovech.ai.services.httpx.AsyncClient",
        lambda **kwargs: original_client(transport=httpx.MockTransport(respond), **kwargs),
    )
    summary = await generate_summary_with_openrouter("Тестовая расшифровка")
    assert summary["title"] == "Тест"
    assert len(calls) == 2


async def test_long_summary_uses_chunks_and_rejects_tiny_final(monkeypatch, settings):
    import json

    settings.openrouter_api_key = SecretStr("test-key")
    settings.openrouter_models = (
        "nvidia/nemotron-3-ultra-550b-a55b:free,nvidia/nemotron-3.5-lightning:free"
    )
    monkeypatch.setattr("slovech.ai.services.get_settings", lambda: settings)
    calls = []
    transcription = "Подробный рассказ об игре и тактике. " * 500
    detailed = "## Матч\n" + "Игрок описывает ход боя и свои решения. " * 70
    detailed += "\n## Итоги\n" + "Команда обсуждает результат и ошибки. " * 40

    def respond(req):
        payload = json.loads(req.content)
        calls.append(payload)
        is_final = "key_points" in payload["messages"][0]["content"]
        if not is_final:
            content = "## Эпизоды\n" + "Конкретное событие и его результат. " * 25
        elif payload["model"].endswith("ultra-550b-a55b:free"):
            content = json.dumps({"title": "Игра", "summary": "Общий обзор.", "key_points": []})
        else:
            content = json.dumps({"title": "Разбор матча", "summary": detailed, "key_points": []})
        return httpx.Response(
            200,
            json={"choices": [{"finish_reason": "stop", "message": {"content": content}}]},
        )

    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        "slovech.ai.services.httpx.AsyncClient",
        lambda **kwargs: original_client(transport=httpx.MockTransport(respond), **kwargs),
    )
    summary = await generate_summary_with_openrouter(transcription)
    assert summary["title"] == "Разбор матча"
    assert len(calls) >= 4
    assert calls[-2]["model"].endswith("ultra-550b-a55b:free")
    assert calls[-1]["model"].endswith("3.5-lightning:free")


@pytest.mark.parametrize("metadata_ok", [True, False])
async def test_long_russian_record_uses_chunk_notes_even_when_metadata_fails(
    monkeypatch, settings, metadata_ok
):
    import json

    settings.openrouter_api_key = SecretStr("test-key")
    settings.openrouter_models = "model-one,model-two"
    monkeypatch.setattr("slovech.ai.services.get_settings", lambda: settings)
    transcription = "Квантовые состояния и результаты опыта. " * 1800
    calls = []

    def respond(req):
        payload = json.loads(req.content)
        calls.append(payload)
        if payload["max_tokens"] == 512:
            content = (
                json.dumps({"title": "Введение в квантовую физику", "key_points": ["Измерение влияет на состояние."]})
                if metadata_ok else "не JSON"
            )
        else:
            index = len([call for call in calls if call["max_tokens"] == 4096])
            content = f"## Квантовый эпизод {index}\n" + "Описание измерения и результата. " * 25
        return httpx.Response(
            200,
            json={"choices": [{"finish_reason": "stop", "message": {"content": content}}]},
        )

    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        "slovech.ai.services.httpx.AsyncClient",
        lambda **kwargs: original_client(transport=httpx.MockTransport(respond), **kwargs),
    )
    summary = await generate_summary_with_openrouter(transcription)
    note_calls = [call for call in calls if call["max_tokens"] == 4096]
    assert len(note_calls) >= 5
    assert all(call["max_tokens"] != 8192 for call in calls)
    assert f"Квантовый эпизод {len(note_calls)}" in summary["summary"]
    assert summary["title"] == (
        "Введение в квантовую физику" if metadata_ok else "Квантовый эпизод 1"
    )


async def test_summary_requires_openrouter_without_gemini_fallback(monkeypatch, settings):
    settings.openrouter_api_key = SecretStr("")
    settings.openrouter_models = ""
    monkeypatch.setattr("slovech.ai.services.get_settings", lambda: settings)
    with pytest.raises(SummaryUnavailable):
        await generate_summary_with_openrouter("Текст")


def test_summary_prompt_requires_detail_without_invention():
    prompt = get_summary_prompt("ru")
    assert "числа" in prompt
    assert "Не придумывай" in prompt
    assert "содержательные разделы" in prompt
    assert "key_points" in prompt
    assert "не более 3" in prompt
    assert "Остальные важные подробности сохрани в summary" in prompt


async def test_nemotron_formats_transcript_without_losing_raw_text(monkeypatch, settings):
    settings.openrouter_api_key = SecretStr("test-key")
    settings.openrouter_models = (
        "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free,liquid/lfm-2.5-2.6b:free"
    )
    monkeypatch.setattr("slovech.ai.services.get_settings", lambda: settings)
    calls = []

    def respond(req):
        calls.append(req)
        payload = __import__("json").loads(req.content)
        assert payload["model"].startswith("nvidia/nemotron-")
        assert "не сокращай" in payload["messages"][0]["content"]
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"finish_reason": "stop", "message": {"content": "Привет, мир.\n\nЭто тест."}}
                ]
            },
        )

    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        "slovech.ai.services.httpx.AsyncClient",
        lambda **kwargs: original_client(transport=httpx.MockTransport(respond), **kwargs),
    )
    result = await generate_formatted_transcription_with_openrouter("привет мир это тест")
    assert result == "Привет, мир.\n\nЭто тест."
    assert len(calls) == 1


async def test_transcript_formatter_rejects_summary_and_keeps_source(monkeypatch, settings):
    settings.openrouter_api_key = SecretStr("test-key")
    settings.openrouter_models = "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free"
    monkeypatch.setattr("slovech.ai.services.get_settings", lambda: settings)

    def respond(_req):
        return httpx.Response(
            200,
            json={"choices": [{"finish_reason": "stop", "message": {"content": "Краткий итог."}}]},
        )

    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        "slovech.ai.services.httpx.AsyncClient",
        lambda **kwargs: original_client(transport=httpx.MockTransport(respond), **kwargs),
    )
    source = "Здесь много важных слов про конфликты и конкретные события."
    assert await generate_formatted_transcription_with_openrouter(source) == source


async def test_worker_saved_record_retries_notification_without_ai(repo, lecture, monkeypatch):
    repo.save(lecture)
    notify = AsyncMock()
    ai = AsyncMock()
    monkeypatch.setattr("slovech.worker.notify", notify)
    monkeypatch.setattr("slovech.worker.generate_summary_with_openrouter", ai)
    await process_queued_job(
        {"id": lecture.id, "user_id": lecture.user_id, "payload": {}}, AsyncMock(), repo
    )
    notify.assert_awaited_once()
    ai.assert_not_called()


async def test_worker_youtube_transcript_end_to_end(repo, monkeypatch):
    monkeypatch.setattr(
        "slovech.worker.fetch_youtube_transcript", AsyncMock(return_value="[LANG:EN]\nhello")
    )
    monkeypatch.setattr(
        "slovech.worker.generate_summary_with_openrouter",
        AsyncMock(return_value={"title": "Title", "summary": "Summary"}),
    )
    notify = AsyncMock()
    monkeypatch.setattr("slovech.worker.notify", notify)
    await process_queued_job(
        {
            "id": "job",
            "user_id": "123",
            "attempts": 1,
            "payload": {"kind": "youtube", "video_id": "abcdefghijk"},
        },
        AsyncMock(),
        repo,
    )
    lecture = repo.get("job", "123")
    assert lecture.transcription == "hello"
    assert lecture.formatted_transcription == "hello"
    assert lecture.language == "en"
    assert lecture.audio_url is None
    assert not list(repo.settings.audio_dir.iterdir())
    notify.assert_awaited_once()


async def test_worker_saves_preferred_translation_and_original(repo, monkeypatch):
    repo.set_preferences("123", interface_language="es")
    monkeypatch.setattr(
        "slovech.worker.fetch_youtube_transcript", AsyncMock(return_value="[LANG:EN]\nhello")
    )
    monkeypatch.setattr(
        "slovech.worker.generate_summary_with_openrouter",
        AsyncMock(return_value={"title": "Original", "summary": "## Original", "key_points": ["Point"]}),
    )
    translate = AsyncMock(return_value={
        "source_language": "en", "translation_language": "es",
        "title_translated": "Traducción", "summary_translated": "## Traducción",
        "key_points_translated": ["Punto"],
    })
    monkeypatch.setattr("slovech.worker.translate_summary_with_openrouter", translate)
    monkeypatch.setattr("slovech.worker.notify", AsyncMock())
    await process_queued_job(
        {"id": "translated-job", "user_id": "123", "payload": {
            "kind": "youtube", "video_id": "abcdefghijk", "output_language": "es",
        }}, AsyncMock(), repo,
    )
    lecture = repo.get("translated-job", "123")
    assert lecture.title == "Original"
    assert lecture.title_translated == "Traducción"
    assert lecture.translation_language == "es"
    translate.assert_awaited_once()


async def test_worker_notifies_before_optional_transcript_formatting(repo, monkeypatch):
    monkeypatch.setattr(
        "slovech.worker.fetch_youtube_transcript", AsyncMock(return_value="[LANG:RU]\nсырой текст")
    )
    monkeypatch.setattr(
        "slovech.worker.generate_summary_with_openrouter",
        AsyncMock(return_value={"title": "Заголовок", "summary": "Конспект"}),
    )
    notified = False

    async def notify_first(*_args):
        nonlocal notified
        notified = True
        assert repo.get("job", "123").summary == "Конспект"

    async def format_after(*_args):
        assert notified
        return "Сырой текст."

    monkeypatch.setattr("slovech.worker.notify", notify_first)
    monkeypatch.setattr(
        "slovech.worker.generate_formatted_transcription_with_openrouter", format_after
    )
    await process_queued_job(
        {
            "id": "job",
            "user_id": "123",
            "attempts": 1,
            "payload": {"kind": "youtube", "video_id": "abcdefghijk"},
        },
        AsyncMock(),
        repo,
    )
    assert repo.get("job", "123").formatted_transcription == "Сырой текст."


async def test_worker_keeps_readable_transcript_when_formatter_fails(repo, monkeypatch):
    source = "Запись содержит важное событие и его последствия. " * 30
    monkeypatch.setattr(
        "slovech.worker.fetch_youtube_transcript",
        AsyncMock(return_value="[LANG:RU]\n" + source),
    )
    monkeypatch.setattr(
        "slovech.worker.generate_summary_with_openrouter",
        AsyncMock(return_value={"title": "Событие", "summary": "Подробный конспект"}),
    )
    monkeypatch.setattr("slovech.worker.notify", AsyncMock())
    monkeypatch.setattr(
        "slovech.worker.generate_formatted_transcription_with_openrouter",
        AsyncMock(side_effect=ProviderError("unavailable")),
    )
    await process_queued_job(
        {
            "id": "job",
            "user_id": "123",
            "attempts": 1,
            "payload": {"kind": "youtube", "video_id": "abcdefghijk"},
        },
        AsyncMock(),
        repo,
    )
    formatted = repo.get("job", "123").formatted_transcription
    assert formatted and "\n\n" in formatted
    assert formatted.replace("\n\n", " ").split() == source.split()


async def test_audio_is_removed_before_summary_generation(repo, monkeypatch):
    from pathlib import Path
    from types import SimpleNamespace

    bot = AsyncMock()
    bot.get_file.return_value = SimpleNamespace(file_path="remote-audio", file_size=5)

    async def download(_source, destination, **_kwargs):
        destination.write(b"audio")

    async def media_process(*args, **_kwargs):
        if args[0] == "ffprobe":
            return '{"format":{"duration":"3"}}'
        Path(args[-1]).write_bytes(b"converted")
        return ""

    async def summary(_text, _language):
        assert not list(repo.settings.audio_dir.iterdir())
        return {"title": "Готово", "summary": "Конспект"}

    bot.download_file.side_effect = download
    monkeypatch.setattr("slovech.worker.run_process", media_process)
    monkeypatch.setattr("slovech.worker.transcribe_audio", AsyncMock(return_value="речь"))
    monkeypatch.setattr("slovech.worker.generate_summary_with_openrouter", summary)
    monkeypatch.setattr(
        "slovech.worker.generate_formatted_transcription_with_openrouter",
        AsyncMock(return_value="Речь."),
    )
    monkeypatch.setattr("slovech.worker.notify", AsyncMock())

    await process_queued_job(
        {
            "id": "job",
            "user_id": "123",
            "attempts": 1,
            "payload": {"kind": "audio", "file_id": "test"},
        },
        bot,
        repo,
    )
    assert repo.get("job", "123").audio_url is None


async def test_failed_conversion_cleans_files(repo, monkeypatch):
    async def download(url, output):
        __import__("pathlib").Path(output).write_bytes(b"broken audio")

    monkeypatch.setattr("slovech.worker.fetch_youtube_transcript", AsyncMock(return_value=None))
    monkeypatch.setattr("slovech.worker.download_youtube_audio", download)
    monkeypatch.setattr(
        "slovech.worker.run_process", AsyncMock(side_effect=RuntimeError("bad media"))
    )
    with pytest.raises(RuntimeError):
        await process_queued_job(
            {
                "id": "job",
                "user_id": "123",
                "attempts": 1,
                "payload": {"kind": "youtube", "video_id": "abcdefghijk", "url": "unused"},
            },
            AsyncMock(),
            repo,
        )
    assert not list(repo.settings.audio_dir.iterdir())
    assert repo.get("job", "123") is None


async def test_subprocess_large_stdout_is_bounded():
    with pytest.raises(RuntimeError, match="output limit"):
        await run_process(sys.executable, "-c", 'print("x" * 5000000)')


async def test_subprocess_download_disk_budget(tmp_path):
    path = tmp_path / "audio"
    with pytest.raises(RuntimeError, match="size limit"):
        await run_process(
            sys.executable,
            "-c",
            'import pathlib,sys,time; pathlib.Path(sys.argv[1]).write_bytes(b"x"*2000); time.sleep(10)',
            str(path),
            file_limit=(path, 1000),
        )


async def test_local_telegram_path_cannot_escape_shared_root(repo, monkeypatch, tmp_path):
    from types import SimpleNamespace

    repo.settings.telegram_local_file_root = tmp_path / "telegram"
    bot = AsyncMock()
    bot.get_file.return_value = SimpleNamespace(file_path="/etc/passwd", file_size=10)
    with pytest.raises(ValueError, match="outside the shared root"):
        await process_queued_job(
            {
                "id": "job",
                "user_id": "123",
                "attempts": 1,
                "payload": {"kind": "audio", "file_id": "test"},
            },
            bot,
            repo,
        )
    bot.download_file.assert_not_called()


async def test_local_telegram_source_is_removed_after_final_failure(repo, monkeypatch, tmp_path):
    from types import SimpleNamespace

    root = tmp_path / "telegram"
    root.mkdir()
    source = root / "large-audio.mp3"
    source.write_bytes(b"audio")
    repo.settings.telegram_local_file_root = root
    bot = AsyncMock()
    bot.get_file.return_value = SimpleNamespace(file_path=str(source), file_size=5)

    async def download(_, destination, **kwargs):
        destination.write(b"audio")

    bot.download_file.side_effect = download
    monkeypatch.setattr("slovech.worker.run_process", AsyncMock(side_effect=RuntimeError("bad")))
    with pytest.raises(RuntimeError):
        await process_queued_job(
            {
                "id": "job",
                "user_id": "123",
                "attempts": 3,
                "payload": {"kind": "audio", "file_id": "test"},
            },
            bot,
            repo,
        )
    assert not source.exists()
