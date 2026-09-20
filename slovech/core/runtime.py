"""Exclusive process ownership on the shared local filesystem."""

import fcntl
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def process_lock(path: Path):
    with path.open("a") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError(f"Another {path.stem} process is running") from exc
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)
