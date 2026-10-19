# backend/timesheet/rag.py
"""
Project RAG status (pure functions). Thresholds live in the Mongo `config` document
(key `rag`), never in code paths; DEFAULT_RAG is only the fallback.

  Red   : any overdue task, OR hours-used % exceeds tasks-done % by more than 25 points,
          OR forecast end is more than 7 days after the planned end
  Amber : gap over 10 points, OR no hours logged for 14+ days, OR forecast end late at all
  Green : otherwise
"""
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable, Optional

from backend.timesheet import rules

DEFAULT_RAG = {
    "red_gap_pts": 25,          # hours-used% minus tasks-done% above this -> red
    "amber_gap_pts": 10,        # ... above this -> amber
    "red_forecast_days": 7,     # forecast end this many days past planned end -> red
    "amber_forecast_days": 0,   # any lateness beyond this -> amber
    "amber_idle_days": 14,      # no hours logged for this many days -> amber
}


@dataclass
class ProjectStats:
    budget_hours: float = 0.0
    hours_used: float = 0.0
    tasks_total: int = 0
    tasks_done: int = 0
    overdue_tasks: int = 0
    days_since_last_entry: Optional[int] = None    # None = nothing logged yet
    planned_end: Optional[date] = None
    forecast_end: Optional[date] = None


def pct(part: float, whole: float) -> float:
    return 0.0 if not whole else round(100.0 * part / whole, 2)


def gap_points(s: ProjectStats) -> float:
    """hours-used % minus tasks-done %."""
    return round(pct(s.hours_used, s.budget_hours) - pct(s.tasks_done, s.tasks_total), 2)


def forecast_days_late(s: ProjectStats) -> Optional[int]:
    if not s.forecast_end or not s.planned_end:
        return None
    return (s.forecast_end - s.planned_end).days


def rag_status(s: ProjectStats, cfg: Optional[dict] = None) -> str:
    c = {**DEFAULT_RAG, **(cfg or {})}
    gap = gap_points(s)
    late = forecast_days_late(s)
    if s.overdue_tasks > 0 or gap > c["red_gap_pts"] or (late is not None and late > c["red_forecast_days"]):
        return "red"
    if (gap > c["amber_gap_pts"]
            or (s.days_since_last_entry is not None and s.days_since_last_entry >= c["amber_idle_days"])
            or (late is not None and late > c["amber_forecast_days"])):
        return "amber"
    return "green"


def forecast_end_date(today: date, project_start: Optional[date], hours_used: float, budget_hours: float,
                      tasks_done_pct: float, holidays: Iterable[date] = ()) -> Optional[date]:
    """Forecast from the average daily burn: work left = budget x (1 - tasks done %), burned at
    hours_used / working days elapsed since the project started. None if there is no burn yet."""
    if not project_start or hours_used <= 0 or budget_hours <= 0:
        return None
    elapsed = max(rules.working_days(project_start, today, holidays), 1)
    burn = hours_used / elapsed
    remaining = budget_hours * (1 - min(max(tasks_done_pct, 0.0), 100.0) / 100.0)
    days_needed = int(-(-remaining // burn)) if burn > 0 else 0         # ceil, in working days
    d, left = today, days_needed
    hol = set(holidays)
    while left > 0:
        d += timedelta(days=1)
        if d.weekday() < 5 and d not in hol:
            left -= 1
    return d
