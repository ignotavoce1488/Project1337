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
        "slovech.worker.transcribe_audio_with_gemini", AsyncMock(return_value="[LANG:RU]\nТест")
    )
    monkeypatch.setattr(
        "slovech.worker.generate_summary_with_openrouter",
        AsyncMock(return_value={"title": "Тест", "summary": "Конспект"}),
    )
    monkeypatch.setattr("slovech.worker.notify", AsyncMock())
    await process_job(
        {
            "id": "media",
            "user_id": "123",
            "attempts": 1,
            "payload": {"kind": "youtube", "video_id": "abcdefghijk", "url": "unused"},
        },
        AsyncMock(),
        repo,
    )
    lecture = repo.get("media", "123")
    assert lecture.audio_url == "/audio/media_1.mp3"
    assert (repo.settings.audio_dir / "media_1.mp3").stat().st_size > 0
    assert not list(repo.settings.audio_dir.glob("raw_*"))
