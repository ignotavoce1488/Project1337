import asyncio
import re
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


async def test_transcript_translation_uses_bounded_chunks_and_survives_retry(
    client, repo, lecture, headers, monkeypatch
):
    from slovech.ai.services import translation_chunks

    original = "Русское предложение с важным фактом. " * 220
    repo.save(lecture.model_copy(update={"language": "ru", "transcription": original}))
    repo.set_preferences("123", interface_language="de")
    endpoint = "/api/lecture/lecture1/transcript-translation"
    assert client.post(endpoint, headers={"X-Telegram-Init-Data": signed(999)}).status_code == 404
    assert client.get(endpoint, headers=headers).json()["state"] == "missing"
    assert client.post(endpoint, headers=headers).json()["state"] == "pending"
    assert client.post(endpoint, headers=headers).json()["state"] == "pending"
    chunks = translation_chunks(original, limit=6000)
    assert len(chunks) > 1
    job = repo.claim()
    assert job["payload"]["chunk_limit"] == 6000
    assert job["payload"]["total_chunks"] == len(chunks)
    repo.save_transcription_part(job["id"], 0, "Erster übersetzter Teil.")
    status = client.get(endpoint, headers=headers).json()
    assert (status["state"], status["completed"], status["total"]) == (
        "running", 1, len(chunks)
    )
    repo.finish(job, "temporary provider error")
    with repo.connection() as db:
        db.execute("UPDATE jobs SET available=0 WHERE id=?", (job["id"],))
    translate = AsyncMock(side_effect=lambda _text, _language: "Zweiter übersetzter Teil.")
    monkeypatch.setattr("slovech.worker.translate_transcription_chunk_with_openrouter", translate)
    job = repo.claim()
    await process_job(job, AsyncMock(), repo)
    repo.finish(job)
    assert translate.await_count == len(chunks) - 1
    saved = repo.get("lecture1", "123")
    assert saved.transcription == original
    assert saved.transcription_translation_language == "de"
    assert saved.transcription_translated.startswith("Erster übersetzter Teil.")
    assert client.get(endpoint, headers=headers).json()["state"] == "ready"
    assert [item["id"] for item in repo.search_lectures("123", "übersetzter")] == ["lecture1"]


async def test_transcript_parts_translate_in_parallel_and_keep_source_order(
    client, repo, lecture, headers, monkeypatch
):
    from slovech.ai.services import translation_chunks

    original = "\n\n".join(f"Часть {index}. " + "Факт. " * 600 for index in range(6))
    assert len(translation_chunks(original, limit=6000)) == 6
    repo.save(lecture.model_copy(update={"language": "ru", "transcription": original}))
    repo.set_preferences("123", interface_language="de")
    assert client.post("/api/lecture/lecture1/transcript-translation", headers=headers).status_code == 200
    job = repo.claim()
    active = 0
    peak = 0

    async def translate(chunk, target):
        nonlocal active, peak
        assert target == "de"
        index = int(re.search(r"Часть (\d+)", chunk).group(1))
        active += 1
        peak = max(peak, active)
        try:
            await asyncio.sleep(.01 * (6 - index))
            return f"Teil {index}."
        finally:
            active -= 1

    monkeypatch.setattr("slovech.worker.translate_transcription_chunk_with_openrouter", translate)
    await process_job(job, AsyncMock(), repo)
    repo.finish(job)
    assert peak == 4
    assert repo.get("lecture1", "123").transcription_translated == "\n\n".join(
        f"Teil {index}." for index in range(6)
    )


def test_optional_transcript_formatting_preserves_new_translation(repo, lecture):
    repo.save(lecture)
    job_id = "translation-job"
    repo.enqueue(job_id, "transcript_translation:lecture1:de", "123", {
        "kind": "transcript_translation", "lecture_id": "lecture1", "target_language": "de",
    })
    job = repo.claim()
    repo.save_transcript_translation(job, "Deutscher Text")
    repo.update_formatted_transcription(lecture.model_copy(update={"formatted_transcription": "Text."}))
    saved = repo.get("lecture1", "123")
    assert saved.formatted_transcription == "Text."
    assert saved.transcription_translated == "Deutscher Text"


def test_retry_of_failed_legacy_transcript_job_uses_fewer_chunks(client, repo, lecture, headers):
    from slovech.ai.services import translation_chunks

    original = "Русское предложение с важным фактом. " * 500
    repo.save(lecture.model_copy(update={"language": "ru", "transcription": original}))
    repo.set_preferences("123", interface_language="de")
    repo.enqueue("legacy-job", "transcript_translation:lecture1:de", "123", {
        "kind": "transcript_translation", "lecture_id": "lecture1", "target_language": "de",
        "total_chunks": len(translation_chunks(original, limit=4000)),
    })
    old_job = repo.claim()
    repo.save_transcription_part(old_job["id"], 0, "Old chunk")
    repo.finish(old_job, "provider failed", terminal=True)
    assert client.post("/api/lecture/lecture1/transcript-translation", headers=headers).json()["state"] == "pending"
    new_job = repo.claim()
    assert new_job["id"] == old_job["id"]
    assert new_job["payload"]["chunk_limit"] == 6000
    assert new_job["payload"]["total_chunks"] == len(translation_chunks(original, limit=6000))
    assert new_job["payload"]["total_chunks"] < old_job["payload"]["total_chunks"]
    assert repo.get_transcription_part(new_job["id"], 0) is None
