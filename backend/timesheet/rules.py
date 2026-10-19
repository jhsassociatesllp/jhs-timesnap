# backend/timesheet/rules.py
"""
Pure business rules for the hours-only daily timesheet (no I/O, fully testable).
Defaults mirror CLAUDE.md; the real values live in the Mongo `config` document
(see daily.py::get_config), so none of these numbers are hard-wired in endpoints.
"""
import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable, Optional, Set

STANDARD_HOURS = 8.5     # net working day
LUNCH_HOURS = 0.5
TOLERANCE_HOURS = 0.5    # |task hours - HRMS net| <= this -> matched
HOURS_STEP = 0.25
MAX_DAY_HOURS = 24.0
FILL_DEADLINE_DAYS = 5   # after the cycle ends


def net_hours(gross: float, lunch: float = LUNCH_HOURS) -> float:
    """HRMS hours are gross (out - in); net = gross - lunch, never negative."""
    return round(max(float(gross) - lunch, 0.0), 2)


def is_working_day(d: date, holidays: Iterable[date] = ()) -> bool:
    return d.weekday() < 5 and d not in set(holidays)


def working_days(start: date, end: date, holidays: Iterable[date] = ()) -> int:
    """Mon-Fri days in [start, end] inclusive, minus holidays. 0 if end < start."""
    if end < start:
        return 0
    hol: Set[date] = set(holidays)
    n, d = 0, start
    while d <= end:
        if d.weekday() < 5 and d not in hol:
            n += 1
        d += timedelta(days=1)
    return n


def budget_hours(start: Optional[date], end: Optional[date],
                 holidays: Iterable[date] = (), allocation_pct: float = 100.0,
                 standard_hours: float = STANDARD_HOURS) -> float:
    """Budget for a task assignment = working days x 8.5 x allocation %.
    NQ has no allocation column, so callers pass 100 and flag it."""
    if not start or not end:
        return 0.0
    return round(working_days(start, end, holidays) * standard_hours * allocation_pct / 100.0, 2)


def within_tolerance(task_hours: float, hrms_net: float, tolerance: float = TOLERANCE_HOURS) -> bool:
    return abs(round(task_hours - hrms_net, 2)) <= tolerance


def difference(task_hours: float, hrms_net: float) -> float:
    return round(task_hours - hrms_net, 2)


def valid_hours(h, step: float = HOURS_STEP) -> bool:
    """Positive, at most 24, in whole steps of `step` (0.25)."""
    try:
        h = float(h)
    except (TypeError, ValueError):
        return False
    if h <= 0 or h > MAX_DAY_HOURS:
        return False
    return abs(h / step - round(h / step)) < 1e-9


def one_task_hours(entry_count: int, hrms_net: Optional[float]):
    """Hours for a day with exactly one entry are locked to HRMS net hours.
    Returns (hours, locked, awaiting_hrms):
      one entry + HRMS present   -> (net, True, False)
      one entry + no HRMS yet    -> (None, True, True)   'awaiting HRMS', filled on upload
      several entries            -> (None, False, False) employee enters hours."""
    if entry_count != 1:
        return None, False, False
    if hrms_net is None:
        return None, True, True
    return round(float(hrms_net), 2), True, False


@dataclass(frozen=True)
class Cycle:
    id: str          # e.g. "2026-10-C1"
    label: str       # e.g. "1-10 Oct 2026"
    start: date
    end: date
    deadline: date   # end + 5 days


def cycle_from_id(cycle_id: str) -> Cycle:
    """Inverse of cycle_for: '2026-10-C2' -> that cycle. Raises ValueError if malformed."""
    try:
        ym, c = str(cycle_id).split("-C")
        year, month = (int(x) for x in ym.split("-"))
        first_day = {"1": 1, "2": 11, "3": 21}[c]
        return cycle_for(date(year, month, first_day))
    except (ValueError, KeyError):
        raise ValueError("bad cycle id")


def cycle_for(d: date) -> Cycle:
    """10-day cycles: 1-10, 11-20, 21-end of month. Deadline = end + 5 days."""
    last = calendar.monthrange(d.year, d.month)[1]
    if d.day <= 10:
        n, s, e = 1, 1, 10
    elif d.day <= 20:
        n, s, e = 2, 11, 20
    else:
        n, s, e = 3, 21, last
    start, end = date(d.year, d.month, s), date(d.year, d.month, e)
    return Cycle(
        id=f"{d.year}-{d.month:02d}-C{n}",
        label=f"{s}-{e} {start.strftime('%b %Y')}",
        start=start, end=end,
        deadline=end + timedelta(days=FILL_DEADLINE_DAYS),
    )
