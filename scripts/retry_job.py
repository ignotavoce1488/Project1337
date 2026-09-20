"""Explicit operator retry of a failed job, preserving its source/result identity."""

import argparse

from slovech.core.config import get_settings
from slovech.core.storage import Repository

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("job_id")
    args = parser.parse_args()
    repo = Repository(get_settings())
    with repo.connection() as db:
        changed = db.execute(
            "UPDATE jobs SET state='pending',attempts=0,available=0,lease_until=NULL,error=NULL WHERE id=? AND state='failed'",
            (args.job_id,),
        ).rowcount
    print("Queued for retry" if changed else "No failed job with this ID")
    raise SystemExit(0 if changed else 1)
