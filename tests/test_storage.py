import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from scripts.migrate_json import migrate
from slovech.core.storage import QueueFull, Repository


def test_durable_queue_dedup_and_exclusive_claim(repo, settings):
    assert repo.enqueue("job1", "update1", "123", {"kind": "audio"})
    assert not repo.enqueue("job2", "update1", "123", {})
    reopened = Repository(settings)
    with ThreadPoolExecutor(max_workers=4) as pool:
        claims = list(pool.map(lambda _: reopened.claim(), range(4)))
    assert len([claim for claim in claims if claim]) == 1
    job = next(claim for claim in claims if claim)
    assert job["attempts"] == 1
    reopened.finish(job)
    assert reopened.claim() is None


def test_expired_lease_retried_then_failed(repo):
    repo.enqueue("job", "update", "123", {})
    for attempt in range(1, 4):
        job = repo.claim()
        assert job["attempts"] == attempt
        with repo.connection() as db:
            db.execute("UPDATE jobs SET lease_until=0")
    assert repo.claim() is None
    with repo.connection() as db:
        assert db.execute("SELECT state FROM jobs").fetchone()[0] == "failed"


def test_retry_and_stale_attempt_cannot_finish(repo):
    repo.enqueue("job", "update", "123", {})
    old = repo.claim()
    with repo.connection() as db:
        db.execute("UPDATE jobs SET lease_until=0")
    current = repo.claim()
    repo.finish(old)
    with repo.connection() as db:
        assert db.execute("SELECT state FROM jobs").fetchone()[0] == "running"
    repo.finish(current, "ProviderError")
    assert repo.claim() is None  # backoff
    with repo.connection() as db:
        db.execute("UPDATE jobs SET available=0")
    job = repo.claim()
    repo.finish(job, "ProviderError")
    assert repo.claim() is None


def test_quota_error_is_terminal_on_first_attempt(repo):
    repo.enqueue("quota-job", "quota-update", "123", {})
    job = repo.claim()
    repo.finish(job, "QuotaExceeded", terminal=True)
    with repo.connection() as db:
        assert tuple(db.execute("SELECT state,error FROM jobs WHERE id='quota-job'").fetchone()) == (
            "failed", "QuotaExceeded"
        )
    assert repo.claim() is None


def test_queue_limits(repo, settings):
    settings.max_user_jobs = 1
    settings.max_pending_jobs = 2
    repo.enqueue("a", "a", "123", {})
    with pytest.raises(QueueFull):
        repo.enqueue("b", "b", "123", {})
    repo.enqueue("b", "b", "456", {})
    with pytest.raises(QueueFull):
        repo.enqueue("c", "c", "789", {})


def test_legacy_migration_rejects_ownerless_and_preserves_originals(repo, lecture, tmp_path):
    source = tmp_path / "legacy"
    source.mkdir()
    (source / "good.json").write_text(lecture.model_dump_json())
    invalid = lecture.model_dump()
    invalid.pop("user_id")
    (source / "ownerless.json").write_text(json.dumps(invalid))
    (source / "broken.json").write_text("{")
    assert migrate(source, repo) == (1, 2)
    assert migrate(source, repo) == (1, 2)
    assert len(repo.list("123")) == 1
    assert len(list(source.iterdir())) == 3
