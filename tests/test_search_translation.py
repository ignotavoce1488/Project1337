from unittest.mock import AsyncMock

from slovech.worker import process_job
from tests.conftest import signed


def test_search_finds_full_transcript_and_is_owner_scoped(client, repo, lecture, headers):
    repo.save(lecture.model_copy(update={"transcription": "Квантовый эксперимент изменил результат."}))
    repo.save(lecture.model_copy(update={"id": "foreign", "user_id": "999",
                                "transcription": "Квантовый секрет другого пользователя."}))
    response = client.get("/api/lectures/search?q=квант", headers=headers)
    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == ["lecture1"]
    assert "Квантовый" in response.json()[0]["preview"]
    assert client.get("/api/lectures/search?q=секрет", headers=headers).json() == []
    assert client.get("/api/lectures/search?q=квант").status_code == 401


async def test_translation_retries_without_retranscribing(client, repo, lecture, headers, monkeypatch):
    repo.save(lecture.model_copy(update={"language": "en"}))
    repo.set_preferences("123", interface_language="es")
    endpoint = "/api/lecture/lecture1/translation"
    assert client.post(endpoint, headers={"X-Telegram-Init-Data": signed(999)}).status_code == 404
    assert client.post(endpoint, headers=headers).json()["state"] == "pending"
    assert client.post(endpoint, headers=headers).json()["state"] == "pending"
    with repo.connection() as db:
        assert db.execute("SELECT count(*) FROM jobs WHERE source='translation:lecture1:es'").fetchone()[0] == 1
    job = repo.claim()
    repo.finish(job, "provider unavailable", terminal=True)
    assert client.get(endpoint, headers=headers).json()["state"] == "failed"
    assert client.post(endpoint, headers=headers).json()["state"] == "pending"
    translate = AsyncMock(return_value={
        "source_language": "en", "translation_language": "es",
        "title_translated": "Una clase", "summary_translated": "## Resumen\nContenido",
        "key_points_translated": ["Primero"],
    })
    monkeypatch.setattr("slovech.worker.translate_summary_with_openrouter", translate)
    job = repo.claim()
    await process_job(job, AsyncMock(), repo)
    repo.finish(job)
    assert client.get(endpoint, headers=headers).json()["state"] == "ready"
    saved = repo.get("lecture1", "123")
    assert saved.title == "A lecture"
    assert saved.title_translated == "Una clase"
    assert saved.transcription == "Text"
    translate.assert_awaited_once()


def test_search_index_clears_with_lecture_deletion(repo, lecture):
    repo.save(lecture.model_copy(update={"summary": "Квантовая записка"}))
    assert repo.search_lectures("123", "квант")
    from slovech.core.privacy import erase_user_rows

    with repo.connection() as db:
        erase_user_rows(db, "123")
        assert db.execute("SELECT count(*) FROM lecture_search WHERE user_id='123'").fetchone()[0] == 0
    assert repo.search_lectures("123", "квант") == []
