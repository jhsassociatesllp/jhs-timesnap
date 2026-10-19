# backend/metrics/store.py
"""Collection handles for the dashboards, in one place so tests can swap them.
Shared collections (entries, submissions, reco, employees, config...) come from backend.cycle.store."""
from backend.database import (
    dashboard_daily_collection,
    hours_daily_collection,
    payroll_cycles_collection,
    project_metrics_collection,
    team_snapshot_collection,
    timesheets_collection,
)


class _MStore:
    hours = hours_daily_collection
    projects = project_metrics_collection
    daily = dashboard_daily_collection
    team = team_snapshot_collection
    legacy = timesheets_collection            # legacy nested Timesheet_data (read-only here)
    payroll_cycles = payroll_cycles_collection


mstore = _MStore()
