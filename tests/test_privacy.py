import asyncio
import hashlib
import os
import sqlite3
import tarfile
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from slovech.bot_handlers.handlers import handle_deletion_choice, handle_revoke
from slovech.core.legal import document_snapshot
from slovech.core.privacy import DAY, complete_deletions, sweep_retention
from slovech.core.storage import ProcessingCancelled, Repository
from slovech.worker import run_job_guarded


def make_backup(repo, destination):
    destination.parent.mkdir(exist_ok=True)
    snapshot = destination.parent / "snapshot.sqlite3"
    with sqlite3.connect(repo.path) as source, sqlite3.connect(snapshot) as target:
        source.backup(target)
    with tarfile.open(destination, "w:gz") as archive:
        archive.add(snapshot, arcname="data/slovech.sqlite3")
    snapshot.unlink()


def test_confirmation_is_owner_scoped_expiring_and_single_use(repo):
    token = repo.deletion_confirmation("123")
    assert not repo.confirm_deletion("456", token)
    assert not repo.confirm_deletion("123", "wrong")
    with repo.connection() as db:
        db.execute("UPDATE deletion_confirmations SET created=0")
    assert not repo.confirm_deletion("123", token)
    token = repo.deletion_confirmation("123")
    assert repo.confirm_deletion("123", token)
    assert not repo.confirm_deletion("123", token)
    assert repo.legal_stage("123") == "deleting"


def test_deletion_blocks_reaccept_and_stale_writes(repo, lecture, client, headers):
    repo.enqueue("job", "source", "123", {})
    job = repo.claim()
    repo.request_deletion("123")
    for write in (
        lambda: repo.accept_legal("123", "terms"),
        lambda: repo.enqueue("newjob", "newsource", "123", {}),
        lambda: repo.save(lecture, job=job),
        lambda: repo.save_transcription_part("job", 0, "should not persist"),
        lambda: repo.touch("123"),
    ):
        with pytest.raises(ProcessingCancelled):
            write()
    assert client.get("/api/lectures", headers=headers).status_code == 403
    assert repo.claim() is None


def test_deletion_scrubs_backups_and_preserves_other_owner(repo, lecture, tmp_path):
    repo.save(lecture)
    repo.save(lecture.model_copy(update={"id": "other", "user_id": "456"}))
    repo.accept_legal("123", "terms")
    repo.accept_legal("123", "consent")
    repo.enqueue("job", "source", "123", {})
    repo.claim()
    repo.save_transcription_part("job", 0, "private raw transcript")
    (repo.settings.audio_dir / "raw_job_1").write_bytes(b"audio")
    (repo.settings.audio_dir / "job_1_part_000.mp3").write_bytes(b"part")
    backup = repo.settings.data_dir / "backups" / "snapshot.tar.gz"
    make_backup(repo, backup)
    previous_mtime = backup.stat().st_mtime
    repo.request_deletion("123")
    restarted = Repository(repo.settings)
    restarted.initialize()
    assert complete_deletions(restarted) == [("123", True)]
    assert complete_deletions(restarted) == []
    assert repo.legal_stage("123") == "terms"
    assert repo.get(lecture.id, "123") is None
    assert repo.get("other", "456") is not None
    assert not list(repo.settings.audio_dir.iterdir())
    assert backup.stat().st_mtime == previous_mtime
    with repo.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM legal_events").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM transcription_parts").fetchone()[0] == 0
        receipt = db.execute("SELECT * FROM deletion_audit").fetchone()
        assert receipt["user_id"] == "123"
        assert 1095 * DAY <= receipt["expires_at"] - receipt["deleted_at"] <= 1096 * DAY
    with tarfile.open(backup) as archive:
        archive.extractall(tmp_path / "restore", filter="data")
    with sqlite3.connect(tmp_path / "restore/data/slovech.sqlite3") as db:
        assert db.execute("SELECT user_id FROM lectures").fetchall() == [("456",)]
        assert db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_invalid_backup_does_not_report_success(repo, lecture):
    repo.save(lecture)
    directory = repo.settings.data_dir / "backups"
    directory.mkdir()
    bad_backup = directory / "broken.tar.gz"
    bad_backup.write_bytes(b"broken")
    repo.request_deletion("123")
    assert complete_deletions(repo) == []
    assert repo.legal_stage("123") == "deleting"
    assert repo.get(lecture.id, "123") is not None
    assert bad_backup.read_bytes() == b"broken"


def test_retention_only_cleans_expired_files_and_inactive_users(repo, tmp_path, lecture):
    repo.save(lecture)
    repo.touch("123")
    repo.touch("456")
    with repo.connection() as db:
        db.execute(
            "UPDATE user_activity SET last_seen=? WHERE user_id='123'", (time.time() - 366 * DAY,)
        )
    stale = repo.settings.audio_dir / "crashed.mp3"
    fresh = repo.settings.audio_dir / "new.mp3"
    stale.write_bytes(b"old")
    fresh.write_bytes(b"new")
    os.utime(stale, (0, 0))
    protected = tmp_path / "outside.mp3"
    protected.write_bytes(b"not ours")
    (repo.settings.audio_dir / "symlink.mp3").symlink_to(protected)
    directory = repo.settings.data_dir / "backups"
    directory.mkdir()
    expired = directory / "expired.tar.gz"
    expired.write_bytes(b"old")
    os.utime(expired, (0, 0))
    sweep_retention(repo)
    assert not stale.exists() and not expired.exists()
    assert fresh.exists() and protected.exists()
    assert repo.legal_stage("123") == "deleting"
    assert repo.legal_stage("456") == "terms"
    assert complete_deletions(repo) == [("123", False)]


async def test_withdrawal_cancels_inflight_ai_and_waits_for_cleanup(repo, monkeypatch):
    repo.enqueue("job", "source", "123", {"kind": "youtube", "video_id": "abcdefghijk"})
    job = repo.claim()
    started = asyncio.Event()
    cleaned = asyncio.Event()
    monkeypatch.setattr(
        "slovech.worker.fetch_youtube_transcript", AsyncMock(return_value="private speech")
    )

    async def slow_summary(*_):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaned.set()

    monkeypatch.setattr("slovech.worker.generate_summary_with_openrouter", slow_summary)
    notify = AsyncMock()
    monkeypatch.setattr("slovech.worker.notify", notify)
    task = asyncio.create_task(run_job_guarded(job, AsyncMock(), repo))
    await asyncio.wait_for(started.wait(), 2)
    repo.request_deletion("123")
    with pytest.raises(ProcessingCancelled):
        await asyncio.wait_for(task, 2)
    assert cleaned.is_set()
    assert not repo.list("123")
    notify.assert_not_called()
    assert complete_deletions(repo) == [("123", True)]


async def test_bot_requires_confirmation_before_erasing(repo, lecture):
    repo.save(lecture)
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=123),
        chat=SimpleNamespace(type="private", id=123),
        answer=AsyncMock(),
        edit_reply_markup=AsyncMock(),
    )
    await handle_revoke(message, repo)
    assert repo.get(lecture.id, "123") is not None
    markup = message.answer.await_args.kwargs["reply_markup"]
    data = markup.inline_keyboard[0][0].callback_data
    query = SimpleNamespace(
        data=data, message=message, from_user=message.from_user, answer=AsyncMock()
    )
    await handle_deletion_choice(query, AsyncMock(), repo)
    assert repo.legal_stage("123") == "deleting"


def test_accepted_texts_are_archived_with_their_hash(repo):
    repo.accept_legal("123", "terms")
    repo.accept_legal("123", "consent")
    with repo.connection() as db:
        rows = db.execute("SELECT * FROM legal_documents").fetchall()
    assert len(rows) >= 4
    for row in rows:
        assert (
            hashlib.sha256((row["content"] + (row["privacy_content"] or "")).encode()).hexdigest()
            == row["version"]
        )
    assert any(row["version"] == document_snapshot("consent")[0] for row in rows)


def test_crash_cleanup_removes_tracked_telegram_and_scratch_copies(repo, tmp_path):
    from slovech.core.privacy import clean_crash_residue

    root = tmp_path / "telegram"
    root.mkdir()
    repo.settings.telegram_local_file_root = root
    media = root / "voice.oga"
    media.write_bytes(b"voice")
    repo.enqueue("job", "source", "123", {})
    job = repo.claim()
    repo.track_temporary_media(job, str(media))
    scratch = repo.settings.data_dir / ".backup-test"
    scratch.mkdir()
    (scratch / "slovech.sqlite3").write_bytes(b"private")
    clean_crash_residue(repo)
    assert not media.exists() and not scratch.exists()
    with repo.connection() as db:
        assert not db.execute("SELECT * FROM temporary_media").fetchall()


def test_evidence_export_is_explicitly_unsigned_and_contains_no_transcript(repo, lecture, tmp_path):
    from scripts.deletion_evidence import export_record

    repo.save(lecture)
    repo.request_deletion("123")
    complete_deletions(repo)
    with repo.connection() as db:
        row = dict(db.execute("SELECT * FROM deletion_audit").fetchone())
    output = tmp_path / "evidence"
    export_record(row, output)
    assert "НЕ ПОДПИСАН" in (output / "act-draft.md").read_text()
    assert lecture.transcription not in (output / "journal.json").read_text()
    assert (output / "journal.json").stat().st_mode & 0o777 == 0o600
