# backend/timesheet/project_health.py
"""Compute RAG inputs for one project on demand (NQ tasks + timesheet_entries hours).
Phase 5 will precompute these nightly into project_metrics; the maths lives in rag.py."""
from datetime import date
from typing import Optional

from backend.cycle.store import config_doc, holidays_set, store
from backend.nq import repository as nq_repo
from backend.timesheet import rag, rules


def rag_config() -> dict:
    return {**rag.DEFAULT_RAG, **(config_doc().get("rag") or {})}


def compute(project_code: str, today: date) -> Optional[dict]:
    """None if the project does not exist in NQ. Raises NQUnavailable if NQ is down."""
    project = nq_repo.get_project(project_code)
    if project is None:
        return None
    tasks = nq_repo.get_tasks_for_project(project_code)
    holidays = {date.fromisoformat(h) for h in holidays_set()}
    budget = sum(rules.budget_hours(a.start_date, a.end_date, holidays)
                 for a in nq_repo.get_assignments_for_project(project_code))
    agg = list(store.entries.aggregate([
        {"$match": {"project_code": project_code, "hours": {"$ne": None}}},
        {"$group": {"_id": None, "h": {"$sum": "$hours"}, "last": {"$max": "$date"}}}]))
    used = round(agg[0]["h"], 2) if agg else 0.0
    last = date.fromisoformat(agg[0]["last"]) if agg and agg[0].get("last") else None
    done = sum(1 for t in tasks if t.is_complete)
    overdue = sum(1 for t in tasks if t.is_overdue)
    done_pct = rag.pct(done, len(tasks))
    stats = rag.ProjectStats(
        budget_hours=round(budget, 2), hours_used=used, tasks_total=len(tasks), tasks_done=done,
        overdue_tasks=overdue, days_since_last_entry=(today - last).days if last else None,
        planned_end=project.end_date,
        forecast_end=rag.forecast_end_date(today, project.start_date, used, budget, done_pct, holidays))
    return {
        "project_code": project.project_code, "project_name": project.project_name,
        "client_name": project.client_name, "planned_end": project.end_date,
        "forecast_end": stats.forecast_end, "budget_hours": stats.budget_hours, "hours_used": used,
        "tasks_total": stats.tasks_total, "tasks_done": done, "overdue_tasks": overdue,
        "gap_points": rag.gap_points(stats), "days_since_last_entry": stats.days_since_last_entry,
        "rag": rag.rag_status(stats, rag_config()),
        "open_tasks": [t for t in tasks if not t.is_complete],
    }
