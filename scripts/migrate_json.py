"""Explicit, idempotent legacy import. Invalid/ownerless records are never published."""

import argparse
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import ValidationError

from slovech.core.config import SAFE_AUDIO_REGEX, get_settings
from slovech.core.models import Lecture
from slovech.core.storage import Repository


def migrate(source: Path, repository: Repository) -> tuple[int, int]:
    imported = rejected = 0
    for path in sorted(source.glob("*.json")):
        try:
            if path.is_symlink():
                raise ValueError("Symlinks are not imported")
            lecture = Lecture.model_validate_json(path.read_text(encoding="utf-8"))
            if lecture.audio_url:
                audio_path = urlsplit(lecture.audio_url).path
                filename = audio_path.removeprefix("/audio/")
                if not audio_path.startswith("/audio/") or not SAFE_AUDIO_REGEX.fullmatch(filename):
                    raise ValueError("Invalid legacy audio URL")
                lecture.audio_url = audio_path
            repository.save(lecture, path.stat().st_mtime)
            imported += 1
        except (OSError, ValidationError, ValueError):
            rejected += 1
            print(f"Rejected: {path.name} (invalid schema or owner; original preserved)")
    return imported, rejected


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    args = parser.parse_args()
    repo = Repository(get_settings())
    repo.initialize()
    imported, rejected = migrate(args.source, repo)
    print(f"Valid records: {imported}; rejected: {rejected}. Originals unchanged.")
    raise SystemExit(1 if rejected else 0)
