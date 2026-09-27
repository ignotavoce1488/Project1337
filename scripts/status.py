"""Local operational status, suitable for a VPS monitoring agent."""

import json
import shutil
import time

from slovech.core.config import get_settings
from slovech.core.storage import Repository

if __name__ == "__main__":
    settings = get_settings()
    repo = Repository(settings)
    with repo.connection() as db:
        counts = dict(db.execute("SELECT state,COUNT(*) FROM jobs GROUP BY state").fetchall())
        oldest = db.execute("SELECT MIN(created) FROM jobs WHERE state='pending'").fetchone()[0]
        deletions = db.execute("SELECT COUNT(*),MIN(requested_at) FROM deletion_requests").fetchone()
    stamp = settings.data_dir / "worker.heartbeat"
    heartbeat_age = time.time() - float(stamp.read_text()) if stamp.exists() else None
    print(
        json.dumps(
            {
                "jobs": counts,
                "oldest_pending_seconds": int(time.time() - oldest) if oldest else 0,
                "worker_heartbeat_age_seconds": heartbeat_age,
                "free_disk_bytes": shutil.disk_usage(settings.data_dir).free,
                "pending_deletions": deletions[0],
                "oldest_deletion_seconds": int(time.time()-deletions[1]) if deletions[1] else 0,
            }
        )
    )
    raise SystemExit(0 if heartbeat_age is not None and heartbeat_age < 60 else 1)
