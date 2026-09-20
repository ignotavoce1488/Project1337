"""Review unreferenced media; --apply deletes only reviewed candidates under a worker lock."""

import argparse
from pathlib import Path

from slovech.core.config import get_settings
from slovech.core.runtime import process_lock
from slovech.core.storage import Repository

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    repo = Repository(settings)
    with process_lock(settings.data_dir / "slovech.worker.lock"):
        with repo.connection() as db:
            referenced = {
                Path(row[0]).name
                for row in db.execute(
                    "SELECT json_extract(payload, '$.audio_url') FROM lectures WHERE json_extract(payload, '$.audio_url') IS NOT NULL"
                )
            }
        for path in sorted(settings.audio_dir.iterdir()):
            if path.is_file() and not path.is_symlink() and path.name not in referenced:
                print(path.name)
                if args.apply:
                    path.unlink()
