import sys
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import SecretStr

from slovech.ai.services import (
    KeyQuotaExceeded,
    ProviderError,
    QuotaExceeded,
    extract_text,
    extract_transcription,
    parse_summary,
    request,
    transcribe_audio_with_gemini,
    upload_file_to_gemini,
)
from slovech.core.process import run_process
from slovech.core.youtube import youtube_video_id
from slovech.worker import BoundedDownload, process_job, transcribe_audio


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


async def test_transcription_switches_keys_and_stops_when_all_exhausted(tmp_path, monkeypatch, settings):
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
            return {"id": "interaction", "status": "completed", "steps": [
                {"type": "model_output", "content": [{"type": "text", "text": "Привет"}]}
            ]}

    monkeypatch.setattr("slovech.ai.services.upload_file_to_gemini", upload)
    monkeypatch.setattr("slovech.ai.services.request", AsyncMock(return_value=Response()))
    exhausted = set()
    assert await transcribe_audio_with_gemini(str(audio), exhausted_keys=exhausted) == "[LANG:RU]\nПривет"
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


async def test_long_audio_is_transcribed_in_chunks(tmp_path, monkeypatch):
    audio = tmp_path / "audio.mp3"
    audio.write_bytes(b"audio")

    async def split(*args, **kwargs):
        (tmp_path / "audio_part_000.mp3").write_bytes(b"one")
        (tmp_path / "audio_part_001.mp3").write_bytes(b"two")

    transcribe = AsyncMock(side_effect=["[LANG:RU]\nПервая", "[LANG:RU]\nВторая"])
    monkeypatch.setattr("slovech.worker.run_process", split)
    monkeypatch.setattr("slovech.worker.transcribe_audio_with_gemini", transcribe)
    assert await transcribe_audio(audio, 4000) == "[LANG:RU]\nПервая\n\nВторая"
    assert transcribe.await_count == 2
    assert not list(tmp_path.glob("audio_part_*.mp3"))


async def test_worker_saved_record_retries_notification_without_ai(repo, lecture, monkeypatch):
    repo.save(lecture)
    notify = AsyncMock()
    ai = AsyncMock()
    monkeypatch.setattr("slovech.worker.notify", notify)
    monkeypatch.setattr("slovech.worker.generate_summary_with_openrouter", ai)
    await process_job(
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
    await process_job(
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
    assert lecture.language == "en"
    assert lecture.audio_url is None
    assert not list(repo.settings.audio_dir.iterdir())
    notify.assert_awaited_once()


async def test_failed_conversion_cleans_files(repo, monkeypatch):
    async def download(url, output):
        __import__("pathlib").Path(output).write_bytes(b"broken audio")

    monkeypatch.setattr("slovech.worker.fetch_youtube_transcript", AsyncMock(return_value=None))
    monkeypatch.setattr("slovech.worker.download_youtube_audio", download)
    monkeypatch.setattr(
        "slovech.worker.run_process", AsyncMock(side_effect=RuntimeError("bad media"))
    )
    with pytest.raises(RuntimeError):
        await process_job(
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
        await process_job(
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
        await process_job(
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
