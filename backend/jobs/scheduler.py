# backend/jobs/scheduler.py
"""
Standalone scheduler process:  python -m backend.jobs.scheduler
  * 20:00 IST every working day -> manager digest (one email per manager)
  * 02:00 IST every day         -> nightly metrics job (hours_daily, project_metrics, dashboards)
A (job, date) row in job_runs with a unique index guarantees a job runs at most once per day
even if two scheduler processes are started; the digest itself is also idempotent (email_log).
Dry run / manual run:  python -m backend.jobs.scheduler --run-now --date 2026-10-14 --dry-run-dir out
"""
import argparse
import logging
import time
from datetime import date, datetime, time as dtime, timedelta
from typing import Callable, Optional

import pytz
from pymongo.errors import DuplicateKeyError

from backend.cycle import digest
from backend.cycle.store import store

log = logging.getLogger("scheduler")
IST = pytz.timezone("Asia/Kolkata")
DIGEST_TIME = dtime(20, 0)
METRICS_TIME = dtime(2, 0)
METRICS_RETRY_MINUTES = 10          # a failed metrics run (e.g. NQ down) is retried at most this often


def _now() -> datetime:
    return datetime.now(IST)


def claim_run(job: str, day: date, retry_after_minutes: int = 0) -> bool:
    """True for exactly one caller per (job, day). A FAILED run may be claimed again once
    retry_after_minutes have passed since it last started."""
    digest.ensure_indexes()
    try:
        now = datetime.utcnow()
        store.job_runs.insert_one({"job": job, "date": day.isoformat(), "started_at": now,
                                   "last_attempt_at": now, "status": "running"})
        return True
    except DuplicateKeyError:
        # a run that FAILED earlier today may be retried by the next tick
        cutoff = datetime.utcnow() - timedelta(minutes=retry_after_minutes)
        res = store.job_runs.update_one(
            {"job": job, "date": day.isoformat(), "status": "failed", "last_attempt_at": {"$lte": cutoff}},
            {"$set": {"status": "running", "last_attempt_at": datetime.utcnow()}})
        return res.modified_count == 1


def run_due_jobs(now: Optional[datetime] = None, digest_fn: Callable = None) -> Optional[list]:
    """Run the digest if it is 20:00 IST or later today and has not run yet. Returns its results
    (or None when nothing ran). Catches up after a restart later in the evening."""
    now = now or _now()
    if now.time() < DIGEST_TIME:
        return None
    day = now.date()
    if not claim_run("digest", day):
        return None
    try:
        results = (digest_fn or digest.send_digests)(day)
        store.job_runs.update_one({"job": "digest", "date": day.isoformat()},
                                  {"$set": {"status": "done", "finished_at": datetime.utcnow(),
                                            "results": results}})
        return results
    except Exception:
        log.exception("digest job failed")
        store.job_runs.update_one({"job": "digest", "date": day.isoformat()}, {"$set": {"status": "failed"}})
        raise


def run_metrics_if_due(now: Optional[datetime] = None, metrics_fn: Callable = None) -> Optional[dict]:
    """Run the nightly metrics job once per day from 02:00 IST (retried every 10 min while it fails)."""
    now = now or _now()
    if now.time() < METRICS_TIME:
        return None
    day = now.date()
    if not claim_run("metrics", day, retry_after_minutes=METRICS_RETRY_MINUTES):
        return None
    try:
        from backend.metrics import job as metrics_job
        fn = metrics_fn or (lambda d: metrics_job.run(d, backfill_days=metrics_job.default_backfill()))
        stats = fn(day)
        store.job_runs.update_one({"job": "metrics", "date": day.isoformat()},
                                  {"$set": {"status": "done", "finished_at": datetime.utcnow(), "results": stats}})
        return stats
    except Exception:
        log.exception("metrics job failed")
        store.job_runs.update_one({"job": "metrics", "date": day.isoformat()},
                                  {"$set": {"status": "failed", "failed_at": datetime.utcnow()}})
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run-now", action="store_true", help="build the digest for --date immediately and exit")
    ap.add_argument("--date", help="YYYY-MM-DD (default: today IST)")
    ap.add_argument("--dry-run-dir", help="write the digest HTML here instead of sending")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    if args.run_now:
        day = date.fromisoformat(args.date) if args.date else _now().date()
        for r in digest.send_digests(day, dry_run_dir=args.dry_run_dir):
            print(r)
        return 0
    log.info("scheduler started (digest at %s IST)", DIGEST_TIME)
    while True:
        try:
            run_metrics_if_due()
        except Exception:
            log.exception("metrics tick failed")
        try:
            run_due_jobs()
        except Exception:
            log.exception("scheduler tick failed")
        time.sleep(30)


if __name__ == "__main__":
    raise SystemExit(main())
