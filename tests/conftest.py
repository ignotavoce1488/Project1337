import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient

from slovech.core.config import Settings
from slovech.core.models import Lecture
from slovech.server import create_app

TOKEN = "123456789:abcdefghijklmnopqrstuvwxyz123456789"


def signed(user_id=123, **overrides):
    data = {"auth_date": str(int(time.time())), "user": json.dumps({"id": user_id})}
    data.update(overrides)
    secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    check = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    data["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(data)


@pytest.fixture
def settings(tmp_path):
    return Settings(
        _env_file=None,
        environment="test",
        bot_token=TOKEN,
        data_dir=tmp_path / "data",
        audio_dir=tmp_path / "audio",
    )


@pytest.fixture
def client(settings):
    app = create_app(settings)
    with TestClient(app) as client:
        yield client


@pytest.fixture
def repo(client):
    return client.app.state.repository


@pytest.fixture
def lecture():
    return Lecture(
        id="lecture1",
        user_id="123",
        title="A lecture",
        summary="## Summary\nContent",
        key_points=["First"],
        transcription="Text",
        created_at="2026-09-16T12:00:00+00:00",
        audio_url="/audio/lecture1.mp3",
    )


@pytest.fixture
def headers():
    return {"X-Telegram-Init-Data": signed()}
