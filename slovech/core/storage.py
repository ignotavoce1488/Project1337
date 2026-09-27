"""SQLite repository for a single-host deployment. All ownership checks live here."""

from __future__ import annotations

import json
import re
import secrets
import sqlite3
import time
import uuid
from contextlib import contextmanager

from slovech.core.config import Settings
from slovech.core.legal import archived_snapshots, document_snapshot, document_version
from slovech.core.models import Lecture


class QueueFull(Exception):
    pass


class ProcessingCancelled(Exception):
    """Privacy withdrawal or deletion invalidated this user's job."""


class TranslationBusy(Exception):
    """Another translation for this recording is already queued or running."""


class Repository:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.path = settings.data_dir / "slovech.sqlite3"

    @contextmanager
    def connection(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA secure_delete=ON")
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
                CREATE VIRTUAL TABLE IF NOT EXISTS lecture_search USING fts5(
                    lecture_id UNINDEXED, user_id UNINDEXED,
                    title, summary, transcription, translation,
                    tokenize='unicode61 remove_diacritics 2'
                );
                BEGIN IMMEDIATE;
                DROP TRIGGER IF EXISTS lecture_search_insert;
                DROP TRIGGER IF EXISTS lecture_search_update;
                DROP TRIGGER IF EXISTS lecture_search_delete;
                CREATE TRIGGER lecture_search_insert AFTER INSERT ON lectures BEGIN
                    INSERT INTO lecture_search(lecture_id,user_id,title,summary,transcription,translation)
                    VALUES(new.id,new.user_id,
                        json_extract(new.payload,'$.title'),
                        coalesce(json_extract(new.payload,'$.summary'),'') || ' ' || coalesce(json_extract(new.payload,'$.key_points'),''),
                        json_extract(new.payload,'$.transcription'),
                        coalesce(json_extract(new.payload,'$.title_translated'),'') || ' ' ||
                        coalesce(json_extract(new.payload,'$.summary_translated'),'') || ' ' ||
                        coalesce(json_extract(new.payload,'$.key_points_translated'),'') || ' ' ||
                        coalesce(json_extract(new.payload,'$.title_ru'),'') || ' ' ||
                        coalesce(json_extract(new.payload,'$.summary_ru'),'') || ' ' ||
                        coalesce(json_extract(new.payload,'$.transcription_translated'),'')
                    );
                END;
                CREATE TRIGGER lecture_search_update AFTER UPDATE OF payload ON lectures BEGIN
                    DELETE FROM lecture_search WHERE lecture_id=old.id;
                    INSERT INTO lecture_search(lecture_id,user_id,title,summary,transcription,translation)
                    VALUES(new.id,new.user_id,
                        json_extract(new.payload,'$.title'),
                        coalesce(json_extract(new.payload,'$.summary'),'') || ' ' || coalesce(json_extract(new.payload,'$.key_points'),''),
                        json_extract(new.payload,'$.transcription'),
                        coalesce(json_extract(new.payload,'$.title_translated'),'') || ' ' ||
                        coalesce(json_extract(new.payload,'$.summary_translated'),'') || ' ' ||
                        coalesce(json_extract(new.payload,'$.key_points_translated'),'') || ' ' ||
                        coalesce(json_extract(new.payload,'$.title_ru'),'') || ' ' ||
                        coalesce(json_extract(new.payload,'$.summary_ru'),'') || ' ' ||
                        coalesce(json_extract(new.payload,'$.transcription_translated'),'')
                    );
                END;
                CREATE TRIGGER lecture_search_delete AFTER DELETE ON lectures BEGIN
                    DELETE FROM lecture_search WHERE lecture_id=old.id;
                END;
                COMMIT;
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, source TEXT UNIQUE NOT NULL, user_id TEXT NOT NULL,
                    payload TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending',
                    attempts INTEGER NOT NULL DEFAULT 0, available REAL NOT NULL,
                    lease_until REAL, error TEXT, created REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS jobs_pending ON jobs(state, available);
                CREATE TABLE IF NOT EXISTS transcription_parts (
                    job_id TEXT NOT NULL, part_index INTEGER NOT NULL,
                    transcript TEXT NOT NULL,
                    PRIMARY KEY(job_id, part_index)
                );
                CREATE TABLE IF NOT EXISTS legal_acceptance (
                    user_id TEXT PRIMARY KEY,
                    terms_version TEXT,
                    terms_accepted_at REAL,
                    consent_version TEXT,
                    consent_accepted_at REAL
                );
                CREATE TABLE IF NOT EXISTS legal_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    document TEXT NOT NULL,
                    action TEXT NOT NULL,
                    version TEXT,
                    occurred_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS legal_events_owner ON legal_events(user_id, occurred_at);
                CREATE TABLE IF NOT EXISTS legal_documents (
                    version TEXT PRIMARY KEY, kind TEXT NOT NULL,
                    content TEXT NOT NULL, privacy_content TEXT, archived_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS deletion_requests (
                    user_id TEXT PRIMARY KEY, requested_at REAL NOT NULL,
                    notify INTEGER NOT NULL DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS deletion_confirmations (
                    user_id TEXT PRIMARY KEY, token TEXT NOT NULL, created REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS user_activity (
                    user_id TEXT PRIMARY KEY, last_seen REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS user_preferences (
                    user_id TEXT PRIMARY KEY, interface_language TEXT NOT NULL DEFAULT 'ru'
                );
                CREATE TABLE IF NOT EXISTS deletion_audit (
                    id TEXT PRIMARY KEY, user_id TEXT NOT NULL,
                    requested_at REAL NOT NULL, deleted_at REAL NOT NULL,
                    expires_at REAL NOT NULL, reason TEXT NOT NULL,
                    categories TEXT NOT NULL, scope TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS temporary_media (
                    job_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, path TEXT NOT NULL
                );
                INSERT OR IGNORE INTO user_activity(user_id,last_seen)
                    SELECT user_id,MAX(stamp) FROM (
                        SELECT user_id,created AS stamp FROM lectures
                        UNION ALL SELECT user_id,created FROM jobs
                        UNION ALL SELECT user_id,occurred_at FROM legal_events
                    ) GROUP BY user_id;
                PRAGMA user_version=1;
            """)
            db.executemany(
                "INSERT OR IGNORE INTO legal_documents VALUES(?,?,?,?,?)",
                ((*snapshot, time.time()) for snapshot in archived_snapshots()),
            )
            db.execute(
                """INSERT INTO lecture_search(lecture_id,user_id,title,summary,transcription,translation)
                   SELECT l.id,l.user_id,
                          json_extract(l.payload,'$.title'),
                          coalesce(json_extract(l.payload,'$.summary'),'') || ' ' || coalesce(json_extract(l.payload,'$.key_points'),''),
                          json_extract(l.payload,'$.transcription'),
                          coalesce(json_extract(l.payload,'$.title_translated'),'') || ' ' ||
                          coalesce(json_extract(l.payload,'$.summary_translated'),'') || ' ' ||
                          coalesce(json_extract(l.payload,'$.key_points_translated'),'') || ' ' ||
                          coalesce(json_extract(l.payload,'$.title_ru'),'') || ' ' ||
                          coalesce(json_extract(l.payload,'$.summary_ru'),'') || ' ' ||
                          coalesce(json_extract(l.payload,'$.transcription_translated'),'')
                   FROM lectures l WHERE NOT EXISTS
                   (SELECT 1 FROM lecture_search s WHERE s.lecture_id=l.id)"""
            )

    def get_preferences(self, user_id: str) -> dict:
        with self.connection() as db:
            row = db.execute(
                "SELECT interface_language FROM user_preferences WHERE user_id=?",
                (user_id,),
            ).fetchone()
        return dict(row) if row else {"interface_language": None}

    def set_preferences(self, user_id: str, *, interface_language: str):
        from slovech.core.languages import LANGUAGES

        if interface_language not in LANGUAGES:
            raise ValueError("Unsupported interface language")
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._require_not_deleting(db, user_id)
            db.execute(
                "INSERT OR IGNORE INTO user_preferences(user_id) VALUES(?)", (user_id,)
            )
            db.execute("UPDATE user_preferences SET interface_language=? WHERE user_id=?",
                       (interface_language, user_id))

    def legal_stage(self, user_id: str) -> str:
        """Return the first document the user has not accepted in its current version."""
        with self.connection() as db:
            if db.execute("SELECT 1 FROM deletion_requests WHERE user_id=?", (user_id,)).fetchone():
                return "deleting"
            row = db.execute(
                "SELECT terms_version, consent_version FROM legal_acceptance WHERE user_id=?",
                (user_id,),
            ).fetchone()
        if not row or row["terms_version"] != document_version("terms"):
            return "terms"
        if row["consent_version"] != document_version("consent"):
            return "consent"
        return "ready"

    def accept_legal(self, user_id: str, kind: str, expected_version: str | None = None):
        if kind not in {"terms", "consent"}:
            raise ValueError("Unknown legal document")
        if kind == "consent" and self.legal_stage(user_id) != "consent":
            raise ValueError("Terms must be accepted first")
        version, content, privacy_content = document_snapshot(kind)
        if expected_version is not None and not version.startswith(expected_version):
            raise ValueError("Document version changed")
        now = time.time()
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._require_not_deleting(db, user_id)
            if kind == "consent":
                accepted = db.execute(
                    "SELECT terms_version FROM legal_acceptance WHERE user_id=?", (user_id,)
                ).fetchone()
                if not accepted or accepted[0] != document_version("terms"):
                    raise ValueError("Terms changed before consent")
            db.execute(
                "INSERT OR IGNORE INTO legal_documents VALUES(?,?,?,?,?)",
                (version, kind, content, privacy_content, now),
            )
            db.execute(
                "INSERT INTO legal_acceptance(user_id) VALUES(?) ON CONFLICT(user_id) DO NOTHING",
                (user_id,),
            )
            if kind == "terms":
                db.execute(
                    "UPDATE legal_acceptance SET terms_version=?, terms_accepted_at=?, "
                    "consent_version=NULL, consent_accepted_at=NULL WHERE user_id=?",
                    (version, now, user_id),
                )
            else:
                db.execute(
                    "UPDATE legal_acceptance SET consent_version=?, consent_accepted_at=? "
                    "WHERE user_id=?",
                    (version, now, user_id),
                )
            db.execute(
                "INSERT INTO legal_events(user_id,document,action,version,occurred_at) "
                "VALUES(?,?,?,?,?)",
                (user_id, kind, "accepted", version, now),
            )
            db.execute(
                "INSERT INTO user_activity VALUES(?,?) ON CONFLICT(user_id) "
                "DO UPDATE SET last_seen=excluded.last_seen",
                (user_id, now),
            )

    def decline_legal(self, user_id: str):
        self.request_deletion(user_id)

    def request_deletion(self, user_id: str, *, notify: bool = True):
        """Block access and writes atomically; the worker then purges files and backups."""
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "INSERT INTO deletion_requests VALUES(?,?,?) ON CONFLICT(user_id) DO NOTHING",
                (user_id, time.time(), int(notify)),
            )
            db.execute("DELETE FROM legal_acceptance WHERE user_id=?", (user_id,))
            db.execute(
                "UPDATE jobs SET state='cancelled',error='PrivacyDeletion',lease_until=NULL "
                "WHERE user_id=? AND state IN ('pending','running')",
                (user_id,),
            )

    def deletion_confirmation(self, user_id: str) -> str:
        token = secrets.token_hex(12)
        with self.connection() as db:
            db.execute(
                "INSERT INTO deletion_confirmations VALUES(?,?,?) ON CONFLICT(user_id) "
                "DO UPDATE SET token=excluded.token,created=excluded.created",
                (user_id, token, time.time()),
            )
        return token

    def confirm_deletion(self, user_id: str, token: str) -> bool:
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT token,created FROM deletion_confirmations WHERE user_id=?",
                (user_id,),
            ).fetchone()
            if (
                not row
                or not secrets.compare_digest(row["token"], token)
                or row["created"] < time.time() - 600
            ):
                return False
            db.execute("DELETE FROM deletion_confirmations WHERE user_id=?", (user_id,))
            db.execute(
                "INSERT INTO deletion_requests VALUES(?,?,1) ON CONFLICT(user_id) DO NOTHING",
                (user_id, time.time()),
            )
            db.execute("DELETE FROM legal_acceptance WHERE user_id=?", (user_id,))
            db.execute(
                "UPDATE jobs SET state='cancelled',error='PrivacyDeletion',lease_until=NULL "
                "WHERE user_id=? AND state IN ('pending','running')",
                (user_id,),
            )
        return True

    def cancel_deletion_confirmation(self, user_id: str, token: str):
        with self.connection() as db:
            db.execute(
                "DELETE FROM deletion_confirmations WHERE user_id=? AND token=?", (user_id, token)
            )

    @staticmethod
    def _require_not_deleting(db, user_id: str):
        if db.execute("SELECT 1 FROM deletion_requests WHERE user_id=?", (user_id,)).fetchone():
            raise ProcessingCancelled()

    def touch(self, user_id: str):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._require_not_deleting(db, user_id)
            db.execute(
                "INSERT INTO user_activity VALUES(?,?) ON CONFLICT(user_id) DO UPDATE "
                "SET last_seen=excluded.last_seen WHERE last_seen<excluded.last_seen-3600",
                (user_id, time.time()),
            )

    def ensure_processing_allowed(self, job: dict):
        with self.connection() as db:
            self._require_job_active(db, job)

    def track_temporary_media(self, job: dict, path: str):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._require_job_active(db, job)
            db.execute(
                "INSERT OR REPLACE INTO temporary_media VALUES(?,?,?)",
                (job["id"], job["user_id"], path),
            )

    def forget_temporary_media(self, job_id: str):
        with self.connection() as db:
            db.execute("DELETE FROM temporary_media WHERE job_id=?", (job_id,))

    def ensure_transcription_allowed(self, job_id: str):
        with self.connection() as db:
            row = db.execute("SELECT user_id,state FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row or row["state"] != "running":
                raise ProcessingCancelled()
            self._require_not_deleting(db, row["user_id"])

    def _require_job_active(self, db, job: dict):
        self._require_not_deleting(db, job["user_id"])
        row = db.execute("SELECT state,attempts FROM jobs WHERE id=?", (job["id"],)).fetchone()
        if not row or row["state"] != "running" or row["attempts"] != job["attempts"]:
            raise ProcessingCancelled()

    def get_transcription_part(self, job_id: str, part_index: int) -> str | None:
        with self.connection() as db:
            row = db.execute(
                "SELECT transcript FROM transcription_parts WHERE job_id=? AND part_index=?",
                (job_id, part_index),
            ).fetchone()
        return row[0] if row else None

    def save_transcription_part(self, job_id: str, part_index: int, transcript: str):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT user_id,state FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row or row["state"] != "running":
                raise ProcessingCancelled()
            self._require_not_deleting(db, row["user_id"])
            db.execute(
                "INSERT INTO transcription_parts(job_id,part_index,transcript) VALUES(?,?,?) "
                "ON CONFLICT(job_id,part_index) DO NOTHING",
                (job_id, part_index, transcript),
            )

    def clear_transcription_parts(self, job_id: str):
        with self.connection() as db:
            db.execute("DELETE FROM transcription_parts WHERE job_id=?", (job_id,))

    def save(self, lecture: Lecture, created: float | None = None, *, job: dict | None = None):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._require_not_deleting(db, lecture.user_id)
            if job is not None:
                self._require_job_active(db, job)
            db.execute(
                "INSERT INTO lectures(id,user_id,created,payload) VALUES (?,?,?,?) ON CONFLICT(id) DO NOTHING",
                (lecture.id, lecture.user_id, created or time.time(), lecture.model_dump_json()),
            )

    def update_formatted_transcription(self, lecture: Lecture):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._require_not_deleting(db, lecture.user_id)
            row = db.execute("SELECT payload FROM lectures WHERE id=? AND user_id=?",
                             (lecture.id, lecture.user_id)).fetchone()
            if not row:
                return
            current = Lecture.model_validate_json(row[0])
            updated = current.model_copy(update={"formatted_transcription": lecture.formatted_transcription})
            db.execute(
                "UPDATE lectures SET payload=? WHERE id=? AND user_id=?",
                (updated.model_dump_json(), lecture.id, lecture.user_id),
            )

    def result_message_id(self, job_id: str) -> int | None:
        with self.connection() as db:
            row = db.execute(
                "SELECT json_extract(payload, '$.result_message_id') FROM jobs WHERE id=?",
                (job_id,),
            ).fetchone()
        return int(row[0]) if row and row[0] is not None else None

    def record_result_message(self, job_id: str, message_id: int):
        with self.connection() as db:
            db.execute(
                "UPDATE jobs SET payload=json_set(payload, '$.result_message_id', ?) WHERE id=?",
                (message_id, job_id),
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
                """SELECT l.id,
                   CASE WHEN json_extract(l.payload,'$.translation_language')=p.interface_language
                             AND json_extract(l.payload,'$.summary_translated') IS NOT NULL
                        THEN json_extract(l.payload,'$.title_translated')
                        WHEN p.interface_language='ru' AND json_extract(l.payload,'$.summary_ru') IS NOT NULL
                        THEN coalesce(json_extract(l.payload,'$.title_ru'),json_extract(l.payload,'$.title'))
                        ELSE json_extract(l.payload,'$.title') END AS title,
                   json_extract(l.payload, '$.created_at') AS created_at,
                   substr(CASE WHEN json_extract(l.payload,'$.translation_language')=p.interface_language
                                    AND json_extract(l.payload,'$.summary_translated') IS NOT NULL
                               THEN json_extract(l.payload,'$.summary_translated')
                               WHEN p.interface_language='ru' AND json_extract(l.payload,'$.summary_ru') IS NOT NULL
                               THEN json_extract(l.payload,'$.summary_ru')
                               ELSE json_extract(l.payload,'$.summary') END,1,120) AS preview,
                   json_array_length(l.payload, '$.key_points') AS key_points_count,
                   json_extract(l.payload, '$.audio_url') IS NOT NULL AS has_audio
                   FROM lectures l LEFT JOIN user_preferences p ON p.user_id=l.user_id
                   WHERE l.user_id=? ORDER BY l.created DESC,l.id DESC LIMIT ? OFFSET ?""",
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

    def search_lectures(self, user_id: str, query: str, limit: int = 50) -> list[dict]:
        tokens = re.findall(r"\w+", query.casefold(), flags=re.UNICODE)[:8]
        if not tokens:
            return []
        match = " ".join('"' + token.replace('"', '') + '"*' for token in tokens)
        with self.connection() as db:
            rows = db.execute(
                """SELECT l.id,
                          CASE WHEN json_extract(l.payload,'$.translation_language')=p.interface_language
                                    AND json_extract(l.payload,'$.summary_translated') IS NOT NULL
                               THEN json_extract(l.payload,'$.title_translated')
                               WHEN p.interface_language='ru' AND json_extract(l.payload,'$.summary_ru') IS NOT NULL
                               THEN coalesce(json_extract(l.payload,'$.title_ru'),json_extract(l.payload,'$.title'))
                               ELSE json_extract(l.payload,'$.title') END AS title,
                          json_extract(l.payload,'$.created_at') AS created_at,
                          snippet(lecture_search,-1,'','',' … ',18) AS preview,
                          json_array_length(l.payload,'$.key_points') AS key_points_count,
                          json_extract(l.payload,'$.audio_url') IS NOT NULL AS has_audio
                   FROM lecture_search JOIN lectures l ON l.id=lecture_search.lecture_id
                   LEFT JOIN user_preferences p ON p.user_id=l.user_id
                   WHERE lecture_search MATCH ? AND lecture_search.user_id=? AND l.user_id=?
                   ORDER BY rank, l.created DESC LIMIT ?""",
                (match, user_id, user_id, limit),
            ).fetchall()
        return [{**dict(row), "preview": (row["preview"] or "").replace("#", "").strip(),
                 "has_audio": bool(row["has_audio"])} for row in rows]

    def translation_status(self, lecture_id: str, user_id: str, language: str) -> str | None:
        with self.connection() as db:
            row = db.execute("SELECT payload FROM lectures WHERE id=? AND user_id=?",
                             (lecture_id, user_id)).fetchone()
            if not row:
                return None
            lecture = Lecture.model_validate_json(row[0])
            if lecture.language == language or (
                lecture.translation_language == language and lecture.summary_translated
            ):
                return "ready"
            job = db.execute("SELECT state FROM jobs WHERE source=? AND user_id=?",
                             (f"translation:{lecture_id}:{language}", user_id)).fetchone()
            return job[0] if job else "missing"

    def enqueue_translation(self, lecture_id: str, user_id: str, language: str) -> str | None:
        source = f"translation:{lecture_id}:{language}"
        now = time.time()
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._require_not_deleting(db, user_id)
            row = db.execute("SELECT payload FROM lectures WHERE id=? AND user_id=?",
                             (lecture_id, user_id)).fetchone()
            if not row:
                return None
            lecture = Lecture.model_validate_json(row[0])
            if lecture.language == language or (
                lecture.translation_language == language and lecture.summary_translated
            ):
                return "ready"
            active = db.execute(
                """SELECT state,source FROM jobs WHERE user_id=? AND state IN ('pending','running')
                   AND json_extract(payload,'$.kind')='translation'
                   AND json_extract(payload,'$.lecture_id')=? LIMIT 1""",
                (user_id, lecture_id),
            ).fetchone()
            if active:
                if active["source"] == source:
                    return active["state"]
                raise TranslationBusy()
            existing = db.execute("SELECT id,state FROM jobs WHERE source=? AND user_id=?",
                                  (source, user_id)).fetchone()
            if existing:
                db.execute(
                    "UPDATE jobs SET state='pending',attempts=0,error=NULL,available=?,lease_until=NULL "
                    "WHERE id=?", (now, existing["id"]),
                )
                return "pending"
            counts = db.execute(
                "SELECT COUNT(*),COALESCE(SUM(user_id=?),0) FROM jobs "
                "WHERE state IN ('pending','running')", (user_id,),
            ).fetchone()
            if counts[0] >= self.settings.max_pending_jobs or counts[1] >= self.settings.max_user_jobs:
                raise QueueFull()
            db.execute(
                "INSERT INTO jobs(id,source,user_id,payload,available,created) VALUES(?,?,?,?,?,?)",
                (uuid.uuid4().hex, source, user_id,
                 json.dumps({"kind": "translation", "lecture_id": lecture_id,
                             "target_language": language}), now, now),
            )
        return "pending"

    def save_translation(self, job: dict, translated: dict):
        lecture_id = job["payload"]["lecture_id"]
        target = job["payload"]["target_language"]
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._require_job_active(db, job)
            row = db.execute("SELECT payload FROM lectures WHERE id=? AND user_id=?",
                             (lecture_id, job["user_id"])).fetchone()
            if not row:
                raise ProcessingCancelled()
            lecture = Lecture.model_validate_json(row[0])
            source_language = translated.get("source_language")
            updates = {}
            if lecture.language == "auto" and isinstance(source_language, str) and re.fullmatch(r"[a-z]{2}", source_language):
                updates["language"] = source_language
            if translated.get("translation_language") == target:
                updates.update({key: translated[key] for key in (
                    "translation_language", "title_translated", "summary_translated",
                    "key_points_translated",
                )})
            else:
                updates.update(translation_language=None, title_translated=None,
                               summary_translated=None, key_points_translated=None)
            updated = Lecture.model_validate({**lecture.model_dump(), **updates})
            db.execute("UPDATE lectures SET payload=? WHERE id=? AND user_id=?",
                       (updated.model_dump_json(), lecture_id, job["user_id"]))

    def transcript_translation_status(self, lecture_id: str, user_id: str, language: str) -> dict | None:
        with self.connection() as db:
            row = db.execute("SELECT payload FROM lectures WHERE id=? AND user_id=?",
                             (lecture_id, user_id)).fetchone()
            if not row:
                return None
            lecture = Lecture.model_validate_json(row[0])
            if lecture.language == language or (
                lecture.transcription_translation_language == language and lecture.transcription_translated
            ):
                return {"state": "ready", "completed": 0, "total": 0}
            job = db.execute("SELECT id,state,payload FROM jobs WHERE source=? AND user_id=?",
                             (f"transcript_translation:{lecture_id}:{language}", user_id)).fetchone()
            if not job:
                return {"state": "missing", "completed": 0, "total": 0}
            completed = db.execute("SELECT COUNT(*) FROM transcription_parts WHERE job_id=?",
                                   (job["id"],)).fetchone()[0]
            total = json.loads(job["payload"]).get("total_chunks", 0)
            return {"state": job["state"], "completed": completed, "total": total}

    def enqueue_transcript_translation(self, lecture_id: str, user_id: str, language: str) -> str | None:
        from slovech.ai.services import TRANSCRIPT_TRANSLATION_CHUNK_LIMIT, translation_chunks

        source = f"transcript_translation:{lecture_id}:{language}"
        now = time.time()
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._require_not_deleting(db, user_id)
            row = db.execute("SELECT payload FROM lectures WHERE id=? AND user_id=?",
                             (lecture_id, user_id)).fetchone()
            if not row:
                return None
            lecture = Lecture.model_validate_json(row[0])
            if lecture.language == language or (
                lecture.transcription_translation_language == language and lecture.transcription_translated
            ):
                return "ready"
            active = db.execute(
                """SELECT state,source FROM jobs WHERE user_id=? AND state IN ('pending','running')
                   AND json_extract(payload,'$.kind')='transcript_translation'
                   AND json_extract(payload,'$.lecture_id')=? LIMIT 1""",
                (user_id, lecture_id),
            ).fetchone()
            if active:
                if active["source"] == source:
                    return active["state"]
                raise TranslationBusy()
            existing = db.execute("SELECT id FROM jobs WHERE source=? AND user_id=?",
                                  (source, user_id)).fetchone()
            if existing:
                total = len(translation_chunks(lecture.transcription, limit=TRANSCRIPT_TRANSLATION_CHUNK_LIMIT))
                db.execute("DELETE FROM transcription_parts WHERE job_id=?", (existing["id"],))
                db.execute(
                    "UPDATE jobs SET state='pending',attempts=0,error=NULL,available=?,lease_until=NULL, "
                    "payload=json_set(payload,'$.total_chunks',?,'$.chunk_limit',?) WHERE id=?",
                    (now, total, TRANSCRIPT_TRANSLATION_CHUNK_LIMIT, existing["id"]),
                )
                return "pending"
            counts = db.execute(
                "SELECT COUNT(*),COALESCE(SUM(user_id=?),0) FROM jobs "
                "WHERE state IN ('pending','running')", (user_id,),
            ).fetchone()
            if counts[0] >= self.settings.max_pending_jobs or counts[1] >= self.settings.max_user_jobs:
                raise QueueFull()
            total = len(translation_chunks(lecture.transcription, limit=TRANSCRIPT_TRANSLATION_CHUNK_LIMIT))
            db.execute(
                "INSERT INTO jobs(id,source,user_id,payload,available,created) VALUES(?,?,?,?,?,?)",
                (uuid.uuid4().hex, source, user_id,
                 json.dumps({"kind": "transcript_translation", "lecture_id": lecture_id,
                             "target_language": language, "total_chunks": total,
                             "chunk_limit": TRANSCRIPT_TRANSLATION_CHUNK_LIMIT}), now, now),
            )
        return "pending"

    def save_transcript_translation(self, job: dict, translated: str):
        if not translated.strip():
            raise ValueError("Empty translated transcript")
        lecture_id = job["payload"]["lecture_id"]
        target = job["payload"]["target_language"]
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._require_job_active(db, job)
            row = db.execute("SELECT payload FROM lectures WHERE id=? AND user_id=?",
                             (lecture_id, job["user_id"])).fetchone()
            if not row:
                raise ProcessingCancelled()
            lecture = Lecture.model_validate_json(row[0])
            updated = lecture.model_copy(update={
                "transcription_translated": translated,
                "transcription_translation_language": target,
            })
            Lecture.model_validate(updated.model_dump())
            db.execute("UPDATE lectures SET payload=? WHERE id=? AND user_id=?",
                       (updated.model_dump_json(), lecture_id, job["user_id"]))

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
            self._require_not_deleting(db, user_id)
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
            db.execute(
                "INSERT INTO user_activity VALUES(?,?) ON CONFLICT(user_id) "
                "DO UPDATE SET last_seen=excluded.last_seen",
                (user_id, now),
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
        state = (
            "done"
            if error is None
            else ("failed" if terminal or job["attempts"] >= 3 else "pending")
        )
        with self.connection() as db:
            db.execute(
                "UPDATE jobs SET state=?,error=?,available=?,lease_until=NULL WHERE id=? AND state='running' AND attempts=?",
                (state, error, time.time() + 30 * job["attempts"], job["id"], job["attempts"]),
            )
            if state in {"done", "failed"}:
                db.execute("DELETE FROM transcription_parts WHERE job_id=?", (job["id"],))

    def recover_running(self):
        """Called only while holding the exclusive worker process lock."""
        with self.connection() as db:
            db.execute(
                "UPDATE jobs SET state=CASE WHEN attempts>=3 THEN 'failed' ELSE 'pending' END, available=0, lease_until=NULL WHERE state='running'"
            )

    def ready(self):
        with self.connection() as db:
            db.execute("SELECT id FROM lectures LIMIT 1").fetchall()
