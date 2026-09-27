"""Remove audio retained by older completed lectures; dry run by default.

Run only while the worker and backup job are stopped. The script touches files
referenced by completed lecture rows, leaving in-progress media alone.
"""

import argparse
import json

from slovech.core.config import SAFE_AUDIO_REGEX, get_settings
from slovech.core.storage import Repository


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Update lectures and delete linked files")
    args = parser.parse_args()
    settings = get_settings()
    repository = Repository(settings)
    if not repository.path.is_file():
        parser.error(f"Database not found: {repository.path}. Set DATA_DIR to the active deployment.")
    audio_root = settings.audio_dir.resolve()
    with repository.connection() as db:
        rows = db.execute(
            "SELECT id, payload FROM lectures WHERE json_extract(payload, '$.audio_url') IS NOT NULL"
        ).fetchall()
        targets = []
        for row in rows:
            lecture = json.loads(row["payload"])
            url = lecture.get("audio_url")
            if not isinstance(url, str) or not url.startswith("/audio/"):
                raise ValueError(f"Invalid audio URL on lecture {row['id']}")
            filename = url.removeprefix("/audio/")
            if not SAFE_AUDIO_REGEX.fullmatch(filename):
                raise ValueError(f"Unsafe audio filename on lecture {row['id']}")
            path = audio_root / filename
            if path.is_symlink() or path.resolve().parent != audio_root:
                raise ValueError(f"Unsafe audio path on lecture {row['id']}")
            targets.append((row["id"], lecture, path))
        print(f"Completed lectures with saved audio: {len(targets)}")
        print(f"Files present: {sum(path.is_file() for _, _, path in targets)}")
        if not args.apply:
            print("Dry run. Stop worker and backup jobs, then pass --apply to remove these files.")
            return
        for lecture_id, lecture, path in targets:
            path.unlink(missing_ok=True)
            lecture["audio_url"] = None
            # Interrupted runs can be resumed: a missing file is harmless.
            with db:
                db.execute(
                    "UPDATE lectures SET payload=? WHERE id=?",
                    (json.dumps(lecture, ensure_ascii=False), lecture_id),
                )
        print("Stored audio links and their referenced files removed.")


if __name__ == "__main__":
    main()
