"""Create a consistent SQLite backup without temporary or retained audio."""

import argparse
import sqlite3
import tarfile
import tempfile
from pathlib import Path

from slovech.core.config import get_settings
from slovech.core.privacy import erase_user_rows
from slovech.core.runtime import process_lock

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    settings = get_settings()
    backup_dir = settings.data_dir / "backups"
    if (
        backup_dir.is_symlink()
        or args.destination.parent.resolve() != backup_dir.resolve()
        or not args.destination.name.endswith(".tar.gz")
    ):
        parser.error(
            "Use DATA_DIR/backups/<name>.tar.gz so retention and privacy deletion cover this snapshot"
        )
    backup_dir.mkdir(mode=0o2770, exist_ok=True)
    if settings.storage_group_writable:
        backup_dir.chmod(0o2770)
    # Stop the worker for a coordinated DB + media snapshot (see README).
    with (
        process_lock(settings.data_dir / "bot.lock"),
        process_lock(settings.data_dir / "slovech.worker.lock"),
        tempfile.TemporaryDirectory(dir=settings.data_dir, prefix=".backup-") as directory,
    ):
        snapshot = Path(directory) / "slovech.sqlite3"
        source = sqlite3.connect(f"file:{settings.data_dir / 'slovech.sqlite3'}?mode=ro", uri=True)
        target = sqlite3.connect(snapshot)
        try:
            source.backup(target)
            target.execute("PRAGMA secure_delete=ON")
            tables = {
                row[0]
                for row in target.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            if "temporary_media" in tables:
                target.execute("DELETE FROM temporary_media")
            if "deletion_requests" in tables:
                for (user_id,) in target.execute(
                    "SELECT user_id FROM deletion_requests"
                ).fetchall():
                    erase_user_rows(target, user_id, keep_request=True)
            target.commit()
            target.execute("VACUUM")
        finally:
            source.close()
            target.close()
        with args.destination.open("xb") as stream:
            args.destination.chmod(0o640 if settings.storage_group_writable else 0o600)
            with tarfile.open(fileobj=stream, mode="w:gz") as archive:
                archive.add(snapshot, arcname="data/slovech.sqlite3")
    print("Backup created. Verify restore on a separate instance before relying on it.")
