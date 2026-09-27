"""Local privacy lifecycle. Called by the single worker between jobs."""

import logging
import os
import shutil
import sqlite3
import tarfile
import tempfile
import time
import uuid
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from slovech.core.config import SAFE_AUDIO_REGEX, SAFE_ID_REGEX
from slovech.core.storage import Repository

logger = logging.getLogger(__name__)
DAY = 86400
BACKUP_TTL = 7 * DAY
AUDIO_TTL = DAY
INACTIVE_TTL = 365 * DAY
JOB_TTL = 7 * DAY


def erase_user_rows(db: sqlite3.Connection, user_id: str, *, keep_request: bool = False):
    """Also supports pre-privacy backups; never interpolates an untrusted table name."""
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if {"jobs", "transcription_parts"} <= tables:
        db.execute(
            "DELETE FROM transcription_parts WHERE job_id IN (SELECT id FROM jobs WHERE user_id=?)",
            (user_id,),
        )
    names = [
        "lectures",
        "jobs",
        "legal_acceptance",
        "legal_events",
        "user_activity",
        "user_preferences",
        "deletion_confirmations",
        "temporary_media",
    ]
    if not keep_request:
        names.append("deletion_requests")
    for name in names:
        if name in tables:
            db.execute(f"DELETE FROM {name} WHERE user_id=?", (user_id,))


def managed_backups(repository: Repository) -> list[Path]:
    root = repository.settings.data_dir
    directory = root / "backups"
    if directory.is_symlink():
        raise RuntimeError("Backup directory must not be a symlink")
    # Legacy snapshots made by the documented command are included in cleanup.
    return sorted({*directory.glob("*.tar.gz"), *root.glob("backup-*.tar.gz")})


def scrub_backup(path: Path, user_id: str):
    """Atomically replace a managed snapshot with an owner-erased SQLite snapshot."""
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("Unexpected managed backup entry")
    old_stat = path.stat()
    with tempfile.TemporaryDirectory(dir=path.parent, prefix=".privacy-") as directory:
        db_path = Path(directory) / "snapshot.sqlite3"
        with tarfile.open(path, "r:gz") as archive:
            members = archive.getmembers()
            if (
                len(members) != 1
                or members[0].name != "data/slovech.sqlite3"
                or not members[0].isfile()
            ):
                raise RuntimeError("Unsupported backup format; deletion needs operator attention")
            with archive.extractfile(members[0]) as source, db_path.open("xb") as target:
                shutil.copyfileobj(source, target)
        with closing(sqlite3.connect(db_path)) as db:
            db.execute("PRAGMA secure_delete=ON")
            with db:
                erase_user_rows(db, user_id)
            db.execute("VACUUM")
            db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        replacement = Path(directory) / "clean.tar.gz"
        with tarfile.open(replacement, "w:gz") as archive:
            archive.add(db_path, arcname="data/slovech.sqlite3")
        replacement.chmod(0o640)
        os.utime(replacement, (old_stat.st_atime, old_stat.st_mtime))
        os.replace(replacement, path)


def purge_user(repository: Repository, user_id: str):
    """The request stays pending on any failure, blocking re-consent until cleanup succeeds."""
    with repository.connection() as db:
        request = db.execute(
            "SELECT requested_at,notify FROM deletion_requests WHERE user_id=?", (user_id,)
        ).fetchone()
        if not request:
            raise RuntimeError("Deletion must be requested before purging")
        job_ids = [r[0] for r in db.execute("SELECT id FROM jobs WHERE user_id=?", (user_id,))]
        urls = [
            r[0]
            for r in db.execute(
                "SELECT json_extract(payload,'$.audio_url') FROM lectures WHERE user_id=?",
                (user_id,),
            )
        ]
        media = [
            r[0] for r in db.execute("SELECT path FROM temporary_media WHERE user_id=?", (user_id,))
        ]
    for path in media:
        remove_telegram_media(repository, Path(path))
    root = repository.settings.audio_dir
    for job_id in job_ids:
        if not SAFE_ID_REGEX.fullmatch(job_id):
            raise RuntimeError("Unsafe job identifier")
        for pattern in (f"raw_{job_id}_*", f"{job_id}_*"):
            for path in root.glob(pattern):
                if path.is_file() or path.is_symlink():
                    path.unlink(missing_ok=True)
    for url in urls:
        if url and url.startswith("/audio/") and SAFE_AUDIO_REGEX.fullmatch(url[7:]):
            (root / url[7:]).unlink(missing_ok=True)
    for backup in managed_backups(repository):
        scrub_backup(backup, user_id)
    with repository.connection() as db:
        erase_user_rows(db, user_id, keep_request=True)
    # Remove remnants from freelist pages and the WAL before completing the request.
    with repository.connection() as db:
        db.execute("VACUUM")
        if db.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0]:
            raise RuntimeError("Privacy checkpoint is busy; will retry")
    with repository.connection() as db:
        deleted = datetime.now(UTC)
        try:
            expiry = deleted.replace(year=deleted.year + 3)
        except ValueError:
            expiry = deleted.replace(year=deleted.year + 3, day=28)
        db.execute(
            "INSERT INTO deletion_audit VALUES(?,?,?,?,?,?,?,?)",
            (
                uuid.uuid4().hex,
                user_id,
                request["requested_at"],
                deleted.timestamp(),
                expiry.timestamp(),
                "user_request" if request["notify"] else "inactivity_365_days",
                "transcripts,summaries,jobs,consent_history,account_activity,local_media",
                "Конспект: активная SQLite, временные файлы приложения, управляемые резервные копии; не Telegram и не внешние AI-поставщики",
            ),
        )
        db.execute("DELETE FROM deletion_requests WHERE user_id=?", (user_id,))


def sweep_retention(repository: Repository):
    now = time.time()
    for backup in managed_backups(repository):
        if (
            not backup.is_symlink()
            and backup.is_file()
            and backup.stat().st_mtime < now - BACKUP_TTL
        ):
            backup.unlink()
    # This folder is reserved exclusively for this application's temporary media.
    for path in repository.settings.audio_dir.iterdir():
        if path.is_file() and not path.is_symlink() and path.stat().st_mtime < now - AUDIO_TTL:
            path.unlink()
    telegram_root = repository.settings.telegram_local_file_root
    if telegram_root and telegram_root.is_dir() and not telegram_root.is_symlink():
        for parent, dirs, files in os.walk(telegram_root, followlinks=False):
            dirs[:] = [name for name in dirs if not (Path(parent) / name).is_symlink()]
            if Path(parent).name not in {"music", "voice", "documents", "videos", "video_notes"}:
                continue
            for name in files:
                path = Path(parent) / name
                if (
                    path.suffix.lower()
                    in {".mp3", ".m4a", ".oga", ".ogg", ".wav", ".flac", ".aac", ".mp4"}
                    and not path.is_symlink()
                    and path.stat().st_mtime < now - AUDIO_TTL
                ):
                    path.unlink()
    with repository.connection() as db:
        db.execute("DELETE FROM deletion_audit WHERE expires_at<?", (now,))
        inactive = [
            r[0]
            for r in db.execute(
                "SELECT user_id FROM user_activity WHERE last_seen<?", (now - INACTIVE_TTL,)
            )
        ]
        db.execute("DELETE FROM deletion_confirmations WHERE created<?", (now - 600,))
        db.execute(
            "DELETE FROM transcription_parts WHERE job_id NOT IN "
            "(SELECT id FROM jobs WHERE state IN ('pending','running'))"
        )
        db.execute(
            "DELETE FROM jobs WHERE state IN ('done','failed','cancelled') AND available<? "
            "AND user_id NOT IN (SELECT user_id FROM deletion_requests)",
            (now - JOB_TTL,),
        )
    for user_id in inactive:
        repository.request_deletion(user_id, notify=False)


def remove_telegram_media(repository: Repository, path: Path):
    root = repository.settings.telegram_local_file_root
    if (
        root is None
        or path.is_symlink()
        or not path.resolve().is_relative_to(root.resolve())
        or path.resolve() == root.resolve()
    ):
        raise RuntimeError("Unsafe temporary Telegram path")
    path.unlink(missing_ok=True)


def clean_crash_residue(repository: Repository):
    """Run with the worker lock before claiming jobs; no live temporary files exist yet."""
    with repository.connection() as db:
        media = db.execute("SELECT job_id,path FROM temporary_media").fetchall()
    for row in media:
        remove_telegram_media(repository, Path(row["path"]))
        repository.forget_temporary_media(row["job_id"])
    # Only our exact scratch filenames; unknown contents are left for operator review.
    for parent in (repository.settings.data_dir, repository.settings.data_dir / "backups"):
        for pattern in (".privacy-*", ".backup-*"):
            for directory in parent.glob(pattern):
                if directory.is_symlink() or not directory.is_dir():
                    raise RuntimeError("Unsafe privacy scratch directory")
                for path in directory.iterdir():
                    if (
                        path.name
                        not in {
                            "snapshot.sqlite3",
                            "slovech.sqlite3",
                            "clean.tar.gz",
                            "snapshot.sqlite3-wal",
                            "snapshot.sqlite3-shm",
                            "snapshot.sqlite3-journal",
                            "slovech.sqlite3-wal",
                            "slovech.sqlite3-shm",
                            "slovech.sqlite3-journal",
                        }
                        or not path.is_file()
                        or path.is_symlink()
                    ):
                        raise RuntimeError("Unexpected privacy scratch contents")
                    path.unlink()
                directory.rmdir()


def complete_deletions(repository: Repository) -> list[tuple[str, bool]]:
    with repository.connection() as db:
        pending = db.execute(
            "SELECT user_id,notify FROM deletion_requests ORDER BY requested_at"
        ).fetchall()
    completed = []
    for row in pending:
        try:
            purge_user(repository, row["user_id"])
            completed.append((row["user_id"], bool(row["notify"])))
        except Exception as exc:
            logger.error("Privacy deletion requires retry type=%s", type(exc).__name__)
    return completed
