import time
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO

import pytest
from docx import Document

from slovech.core.auth import verify_telegram_init_data
from tests.conftest import TOKEN, signed


def test_signature_valid_and_tampered():
    assert verify_telegram_init_data(signed(), TOKEN)["id"] == 123
    assert verify_telegram_init_data(signed().replace("123", "124"), TOKEN) is None


@pytest.mark.parametrize(
    "fields",
    [
        {"auth_date": "0"},
        {"auth_date": str(int(time.time()) - 4000)},
        {"auth_date": str(int(time.time()) + 1000)},
        {"auth_date": ""},
        {"user": "{}"},
        {"user": '{"id":true}'},
        {"user": '{"id":"../../etc"}'},
        {"user": "[]"},
    ],
)
def test_reject_invalid_signed_claims(fields):
    assert verify_telegram_init_data(signed(**fields), TOKEN) is None


def test_reject_duplicate_claim():
    assert verify_telegram_init_data(signed() + "&auth_date=0", TOKEN) is None


@pytest.mark.parametrize(
    "path",
    [
        "/api/lectures",
        "/api/lecture/latest",
        "/api/lecture/lecture1",
        "/api/download/lecture1",
        "/audio/lecture1.mp3",
    ],
)
def test_anonymous_denied(client, path):
    assert client.get(path).status_code == 401
    assert client.get(path, params={"init_data": signed()}).status_code == 401


def test_ownership_all_routes(client, repo, lecture, headers, settings):
    repo.save(lecture)
    (settings.audio_dir / "lecture1.mp3").write_bytes(b"audio")
    foreign = {"X-Telegram-Init-Data": signed(999)}
    for path in ["/api/lecture/lecture1", "/api/download/lecture1", "/audio/lecture1.mp3"]:
        assert client.get(path, headers=foreign).status_code == 404
        result = client.get(path, headers=headers)
        assert result.status_code == 200
        assert result.headers["cache-control"] == "no-store"
    assert client.get("/api/lectures", headers=foreign).json() == []
    assert client.get("/api/lecture/latest", headers=foreign).json() == {"empty": True}
    assert client.get("/api/lecture/latest", headers=headers).json()["id"] == lecture.id


def test_audio_symlink_denied(client, repo, lecture, headers, settings, tmp_path):
    repo.save(lecture)
    outside = tmp_path / "secret"
    outside.write_bytes(b"secret")
    (settings.audio_dir / "lecture1.mp3").symlink_to(outside)
    assert client.get("/audio/lecture1.mp3", headers=headers).status_code == 404


def test_docx_concurrent_in_memory(client, repo, lecture, headers):
    repo.save(lecture)

    def download(_):
        response = client.get("/api/download/lecture1", headers=headers)
        assert response.status_code == 200
        return Document(BytesIO(response.content)).paragraphs[0].text

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert list(pool.map(download, range(8))) == ["A lecture"] * 8


def test_pagination_and_input_validation(client, repo, lecture, headers):
    for i in range(5):
        repo.save(lecture.model_copy(update={"id": f"item{i}"}), i + 1)
    result = client.get("/api/lectures?limit=2&offset=1", headers=headers)
    assert [item["id"] for item in result.json()] == ["item3", "item2"]
    assert client.get("/api/lectures?limit=10000", headers=headers).status_code == 422
    assert client.get("/api/download/item0?lang=bad", headers=headers).status_code == 422
    assert client.get("/api/lecture/bad!", headers=headers).status_code == 400


def test_admin_disabled_and_query_secret_rejected(client, settings):
    assert client.get("/api/lectures", headers={"X-Admin-Secret": "x"}).status_code == 401
    settings.admin_secret = __import__("pydantic").SecretStr("a" * 32)
    settings.admin_user_id = 123
    assert client.get("/api/lectures?admin_key=" + "a" * 32).status_code == 401
    assert client.get("/api/lectures", headers={"X-Admin-Secret": "a" * 32}).status_code == 200
    assert (
        client.get("/api/lectures?user_id=../x", headers={"X-Admin-Secret": "a" * 32}).status_code
        == 400
    )


def test_static_health_and_security_headers(client):
    for path in ["/health", "/ready", "/app", "/static/js/app.js"]:
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers["x-content-type-options"] == "nosniff"
        assert "object-src" in response.headers["content-security-policy"]


def test_rate_limit_ignores_spoofed_forwarding(client, headers):
    for i in range(120):
        assert (
            client.get("/api/lectures", headers={**headers, "X-Forwarded-For": str(i)}).status_code
            == 200
        )
    response = client.get("/api/lectures", headers=headers)
    assert response.status_code == 429
    assert "retry-after" in response.headers
    assert "x-request-id" in response.headers
    assert client.get("/health").status_code == 200


def test_history_projection_and_count_are_owner_scoped(client, repo, lecture, headers):
    repo.save(lecture)
    assert client.get("/api/lectures/count", headers=headers).json() == {"count": 1}
    assert client.get(
        "/api/lectures/count", headers={"X-Telegram-Init-Data": signed(999)}
    ).json() == {"count": 0}
    payload = client.get("/api/lectures", headers=headers).json()[0]
    assert "transcription" not in payload
    assert payload["key_points_count"] == 1
    assert payload["has_audio"] is True
