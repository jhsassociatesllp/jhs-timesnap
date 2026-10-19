# backend/metrics/job.py
"""
Nightly metrics job (02:00 IST): rebuild the pre-aggregated data the dashboards read.
  1. hours_daily     - from timesheet_entries + legacy Timesheet_data (no NQ needed)
  2. dashboard_daily - compliance / unplanned / reco per manager for the last few days (no NQ needed)
  3. project_metrics + team_snapshot - need Nexus Quant (raises NQUnavailable if it is down; the job
     is then retried by the scheduler, and parts 1-2 are already saved)
Idempotent: running a day twice overwrites that day, never duplicates.
"""
import logging
from datetime import date, timedelta
from typing import Dict, Optional

from backend.cycle.store import config_doc, store
from backend.metrics import aggregate as agg
from backend.metrics.store import mstore
from backend.nq import repository as nq_repo
from backend.timesheet import rag

log = logging.getLogger("metrics")
RECENT_DAYS = 3             # compliance is recomputed for the last N days (reco changes after HRMS uploads)
HOURS_WINDOW_DAYS = 45      # incremental hours rebuild window once history exists


def run(day: date, backfill_days: int = 0, full_history: bool = False) -> Dict[str, int]:
    """day = the job date (IST). Snapshots are dated `day` and describe the state at the end of day-1.
    backfill_days: also (re)compute dashboard_daily for that many past days (first run: 90).
    project_metrics / team_snapshot are NOT backfilled: NQ only knows its current state, so a past
    snapshot would be invented."""
    stats: Dict[str, int] = {}
    agg.ensure_indexes()

    first_run = mstore.hours.count_documents({}, limit=1) == 0
    since: Optional[date] = None if (full_history or first_run) else day - timedelta(days=HOURS_WINDOW_DAYS)
    stats["hours_rows"] = agg.build_hours_daily(since)["rows"]

    days_back = max(backfill_days, RECENT_DAYS)
    stats["daily_rows"] = sum(agg.save_dashboard_daily(d, agg.compute_dashboard_daily(d))
                              for d in (day - timedelta(days=i) for i in range(days_back, 0, -1)))

    cfg = {**rag.DEFAULT_RAG, **(config_doc().get("rag") or {})}
    users = nq_repo.list_users()
    projects = nq_repo.list_active_projects()
    tasks = nq_repo.list_tasks_of_active_projects()
    stats["projects"] = agg.save_project_metrics(day, agg.compute_project_metrics(day, projects, tasks, users, cfg))
    stats["team_rows"] = agg.save_team_snapshot(day, agg.compute_team_snapshot(day, tasks, users))
    log.info("metrics job %s: %s", day.isoformat(), stats)
    return stats


def default_backfill() -> int:
    """90 days of compliance history the first time, otherwise just the recent days."""
    return 90 if mstore.daily.count_documents({}, limit=1) == 0 else 0
