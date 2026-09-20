"""Isolated browser-test application: no real accounts or provider traffic."""

import tempfile
from pathlib import Path

import uvicorn

from slovech.core.config import Settings
from slovech.core.models import Lecture
from slovech.core.storage import Repository
from slovech.server import create_app
from tests.conftest import TOKEN

if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as directory:
        settings = Settings(
            _env_file=None,
            environment="test",
            bot_token=TOKEN,
            data_dir=Path(directory) / "data",
            audio_dir=Path(directory) / "audio",
        )
        repository = Repository(settings)
        repository.initialize()
        for i in range(101):
            repository.save(
                Lecture(
                    id=f"lecture{i}",
                    user_id="123",
                    title=f"Lecture {i}",
                    summary="## Summary\nEnglish text",
                    title_ru=f"Лекция {i}",
                    summary_ru="## Конспект\nРусский текст",
                    key_points=["Main point"],
                    key_points_ru=["Главная мысль"],
                    transcription="Hello world.\n\nSecond paragraph.",
                    language="en",
                    created_at="2026-09-16T12:00:00Z",
                ),
                i + 1,
            )
        uvicorn.run(create_app(settings), host="127.0.0.1", port=8765, access_log=False)
