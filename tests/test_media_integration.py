import shutil
import wave
from unittest.mock import AsyncMock

import pytest

from slovech.worker import process_job


@pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
    reason="Requires system ffmpeg and ffprobe (installed in CI and Docker)",
)
async def test_real_wav_to_mp3_pipeline(repo, monkeypatch):
    async def download(url, destination):
        with wave.open(destination, "wb") as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(16000)
            stream.writeframes(b"\x00\x00" * 16000)

    monkeypatch.setattr("slovech.worker.fetch_youtube_transcript", AsyncMock(return_value=None))
    monkeypatch.setattr("slovech.worker.download_youtube_audio", download)
    monkeypatch.setattr(
        "slovech.worker.transcribe_audio_with_aitunnel", AsyncMock(return_value="[LANG:RU]\nТест")
    )
    monkeypatch.setattr(
        "slovech.worker.generate_summary_with_openrouter",
        AsyncMock(return_value={"title": "Тест", "summary": "Конспект"}),
    )
    monkeypatch.setattr("slovech.worker.notify", AsyncMock())
    repo.enqueue(
        "media", "source", "123", {"kind": "youtube", "video_id": "abcdefghijk", "url": "unused"}
    )
    await process_job(repo.claim(), AsyncMock(), repo)
    lecture = repo.get("media", "123")
    assert lecture.audio_url is None
    assert not list(repo.settings.audio_dir.iterdir())
