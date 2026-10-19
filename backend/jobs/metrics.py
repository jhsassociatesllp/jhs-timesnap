# backend/jobs/metrics.py
"""
Manual / backfill run of the nightly metrics job:
  python -m backend.jobs.metrics                      # today (IST), 90 days of compliance history on the first run
  python -m backend.jobs.metrics --date 2026-10-19 --backfill 90
  python -m backend.jobs.metrics --full               # rebuild hours_daily from the whole history
"""
import argparse
import logging
from datetime import date, datetime

import pytz

from backend.metrics import job


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", help="job date YYYY-MM-DD (default: today IST)")
    ap.add_argument("--backfill", type=int, help="also recompute compliance for this many past days")
    ap.add_argument("--full", action="store_true", help="rebuild hours_daily from the full history")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    day = date.fromisoformat(args.date) if args.date else datetime.now(pytz.timezone("Asia/Kolkata")).date()
    backfill = args.backfill if args.backfill is not None else job.default_backfill()
    print(job.run(day, backfill_days=backfill, full_history=args.full))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
