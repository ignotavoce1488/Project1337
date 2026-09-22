"""SQLite repository for a single-host deployment. All ownership checks live here."""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager

from slovech.core.config import Settings
from slovech.core.models import Lecture


class QueueFull(Exception):
    pass


class Repository:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.path = settings.data_dir / "slovech.sqlite3"

    @contextmanager
    def connection(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self):
        self.settings.prepare()
        with self.connection() as db:
            db.execute("PRAGMA journal_mode=WAL")
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise RuntimeError("Unsupported database schema")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS lectures (
                    id TEXT PRIMARY KEY, user_id TEXT NOT NULL,
                    created REAL NOT NULL, payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS lectures_owner ON lectures(user_id, created DESC);
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, source TEXT UNIQUE NOT NULL, user_id TEXT NOT NULL,
                    payload TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending',
                    attempts INTEGER NOT NULL DEFAULT 0, available REAL NOT NULL,
                    lease_until REAL, error TEXT, created REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS jobs_pending ON jobs(state, available);
                PRAGMA user_version=1;
            """)

    def save(self, lecture: Lecture, created: float | None = None):
        with self.connection() as db:
            db.execute(
                "INSERT INTO lectures(id,user_id,created,payload) VALUES (?,?,?,?) ON CONFLICT(id) DO NOTHING",
                (lecture.id, lecture.user_id, created or time.time(), lecture.model_dump_json()),
            )

    def get(self, lecture_id: str, user_id: str) -> Lecture | None:
        with self.connection() as db:
            row = db.execute(
                "SELECT payload FROM lectures WHERE id=? AND user_id=?", (lecture_id, user_id)
            ).fetchone()
        return Lecture.model_validate_json(row[0]) if row else None

    def list(self, user_id: str, limit: int = 100, offset: int = 0) -> list[Lecture]:
        with self.connection() as db:
            rows = db.execute(
                "SELECT payload FROM lectures WHERE user_id=? ORDER BY created DESC,id DESC LIMIT ? OFFSET ?",
                (user_id, limit, offset),
            ).fetchall()
        return [Lecture.model_validate_json(row[0]) for row in rows]

    def count(self, user_id: str) -> int:
        with self.connection() as db:
            return db.execute(
                "SELECT COUNT(*) FROM lectures WHERE user_id=?", (user_id,)
            ).fetchone()[0]

    def previews(self, user_id: str, limit: int, offset: int) -> list[dict]:
        # Do not hydrate full transcripts just to render the history list.
        with self.connection() as db:
            rows = db.execute(
                """SELECT id, json_extract(payload, '$.title') AS title,
                   json_extract(payload, '$.created_at') AS created_at,
                   substr(json_extract(payload, '$.summary'),1,120) AS preview,
                   json_array_length(payload, '$.key_points') AS key_points_count,
                   json_extract(payload, '$.audio_url') IS NOT NULL AS has_audio
                   FROM lectures WHERE user_id=? ORDER BY created DESC,id DESC LIMIT ? OFFSET ?""",
                (user_id, limit, offset),
            ).fetchall()
        return [
            {
                **dict(row),
                "preview": row["preview"].replace("#", "").strip(),
                "has_audio": bool(row["has_audio"]),
            }
            for row in rows
        ]

    def owns_audio(self, filename: str, user_id: str) -> bool:
        with self.connection() as db:
            return (
                db.execute(
                    "SELECT 1 FROM lectures WHERE user_id=? AND json_extract(payload, '$.audio_url')=? LIMIT 1",
                    (user_id, f"/audio/{filename}"),
                ).fetchone()
                is not None
            )

    def enqueue(self, job_id: str, source: str, user_id: str, payload: dict) -> bool:
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM jobs WHERE source=?", (source,)).fetchone():
                return False
            counts = db.execute(
                "SELECT COUNT(*), COALESCE(SUM(user_id=?),0) FROM jobs WHERE state IN ('pending','running')",
                (user_id,),
            ).fetchone()
            if (
                counts[0] >= self.settings.max_pending_jobs
                or counts[1] >= self.settings.max_user_jobs
            ):
                raise QueueFull()
            now = time.time()
            db.execute(
                "INSERT INTO jobs(id,source,user_id,payload,available,created) VALUES(?,?,?,?,?,?)",
                (job_id, source, user_id, json.dumps(payload), now, now),
            )
        return True

    def claim(self) -> dict | None:
        now = time.time()
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "UPDATE jobs SET state='failed',error='Worker lease expired' WHERE state='running' AND lease_until<? AND attempts>=3",
                (now,),
            )
            row = db.execute(
                "SELECT * FROM jobs WHERE (state='pending' AND available<=?) OR (state='running' AND lease_until<? AND attempts<3) ORDER BY created LIMIT 1",
                (now, now),
            ).fetchone()
            if not row:
                return None
            db.execute(
                "UPDATE jobs SET state='running',attempts=attempts+1,lease_until=? WHERE id=?",
                (now + self.settings.job_timeout_seconds + 120, row["id"]),
            )
        return {**dict(row), "payload": json.loads(row["payload"]), "attempts": row["attempts"] + 1}

    def finish(self, job: dict, error: str | None = None, *, terminal: bool = False):
        state = "done" if error is None else ("failed" if terminal or job["attempts"] >= 3 else "pending")
        with self.connection() as db:
            db.execute(
                "UPDATE jobs SET state=?,error=?,available=?,lease_until=NULL WHERE id=? AND state='running' AND attempts=?",
                (state, error, time.time() + 30 * job["attempts"], job["id"], job["attempts"]),
            )

    def recover_running(self):
        """Called only while holding the exclusive worker process lock."""
        with self.connection() as db:
            db.execute(
                "UPDATE jobs SET state=CASE WHEN attempts>=3 THEN 'failed' ELSE 'pending' END, available=0, lease_until=NULL WHERE state='running'"
            )

    def ready(self):
        with self.connection() as db:
            db.execute("SELECT id FROM lectures LIMIT 1").fetchall()
