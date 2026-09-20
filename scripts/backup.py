"""Create a consistent SQLite backup and associated audio archive. Originals untouched."""

import argparse
import sqlite3
import tarfile
import tempfile
from pathlib import Path

from slovech.core.config import get_settings
from slovech.core.runtime import process_lock

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    settings = get_settings()
    # Stop the worker for a coordinated DB + media snapshot (see README).
    with (
        process_lock(settings.data_dir / "bot.lock"),
        process_lock(settings.data_dir / "slovech.worker.lock"),
        tempfile.TemporaryDirectory(dir=settings.data_dir) as directory,
    ):
        snapshot = Path(directory) / "slovech.sqlite3"
        source = sqlite3.connect(f"file:{settings.data_dir / 'slovech.sqlite3'}?mode=ro", uri=True)
        target = sqlite3.connect(snapshot)
        try:
            source.backup(target)
        finally:
            source.close()
            target.close()
        with args.destination.open("xb") as stream:
            args.destination.chmod(0o600)
            with tarfile.open(fileobj=stream, mode="w:gz") as archive:
                archive.add(snapshot, arcname="data/slovech.sqlite3")
                archive.add(settings.audio_dir, arcname="audio")
    print("Backup created. Verify restore on a separate instance before relying on it.")
