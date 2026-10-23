# backend/timesheet/rules.py
"""
Pure business rules for the hours-only daily timesheet (no I/O, fully testable).
Defaults mirror CLAUDE.md; the real values live in the Mongo `config` document
(see daily.py::get_config), so none of these numbers are hard-wired in endpoints.
"""
import calendar
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
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


WEEK_OFF_DEFAULT = (5, 6)          # Saturday, Sunday (Monday is 0); admins can change it


def working_days(start: date, end: date, holidays: Iterable[date] = (), week_off: Iterable[int] = WEEK_OFF_DEFAULT) -> int:
    """Days in [start, end] inclusive that are not a week-off day (default Sat/Sun) and not a holiday. 0 if end < start."""
    if end < start:
        return 0
    hol: Set[date] = set(holidays)
    off = set(week_off)
    n, d = 0, start
    while d <= end:
        if d.weekday() not in off and d not in hol:
            n += 1
        d += timedelta(days=1)
    return n


def budget_hours(start: Optional[date], end: Optional[date],
                 holidays: Iterable[date] = (), allocation_pct: float = 100.0,
                 standard_hours: float = STANDARD_HOURS, week_off: Iterable[int] = WEEK_OFF_DEFAULT) -> float:
    """Budget for a task assignment = working days x 8.5 x allocation %.
    NQ has no allocation column, so callers pass 100 and flag it."""
    if not start or not end:
        return 0.0
    return round(working_days(start, end, holidays, week_off) * standard_hours * allocation_pct / 100.0, 2)


def within_tolerance(task_hours: float, hrms_net: float, tolerance: float = TOLERANCE_HOURS) -> bool:
    return abs(round(task_hours - hrms_net, 2)) <= tolerance


def difference(task_hours: float, hrms_net: float) -> float:
    return round(task_hours - hrms_net, 2)


def project_hours_errors(entries, day_off_locations, max_per_row: float = MAX_DAY_HOURS,
                         max_per_day: float = MAX_DAY_HOURS):
    """Submit-time check of the hours an employee TYPES on the timesheet (HRMS is compared later, in the
    reconciliation). Every working-day row needs hours > 0 and <= 24 with at most 2 decimals; a day's rows
    together cannot exceed 24. Day-off rows (Leave / PHY / Week Off) carry no hours. Row numbers are 1-based
    positions in `entries`, matching the other submit checks."""
    off = set(day_off_locations)
    errors, per_day = [], {}
    for i, e in enumerate(entries, start=1):
        if (e.get("location", "") or "").strip() in off:
            continue
        try:
            h = float(str(e.get("projectHours", "")).strip())
        except (TypeError, ValueError):
            h = None
        if h is None or not (0 < h <= max_per_row) or round(h, 2) != h:
            errors.append(f"Row {i}: enter project hours (more than 0 and at most {max_per_row:g}, up to 2 decimals)")
            continue
        d = str(e.get("date", "") or "")[:10]
        per_day[d] = round(per_day.get(d, 0.0) + h, 2)
    for d, total in sorted(per_day.items()):
        if total > max_per_day:
            errors.append(f"{d}: total hours {total:g} are more than {max_per_day:g} for one day")
    return errors


def valid_hours(h, step: float = HOURS_STEP) -> bool:
    """Positive, at most 24, in whole steps of `step` (0.25)."""
    try:
        h = float(h)
    except (TypeError, ValueError):
        return False
    if h <= 0 or h > MAX_DAY_HOURS:
        return False
    return abs(h / step - round(h / step)) < 1e-9


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


def payroll_id_for_cycle(cycle_id: str) -> str:
    """The classic payroll (21st to 20th) a 10-day cycle belongs to, named by the month it ENDS in.
    '2026-09-C3' (21-30 Sep), '2026-10-C1' and '2026-10-C2' all belong to payroll '2026-10' (21 Sep - 20 Oct)."""
    cyc = cycle_from_id(cycle_id)
    y, m = cyc.start.year, cyc.start.month
    if cycle_id.endswith("C3"):
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return f"{y}-{m:02d}"


def payroll_label(payroll_id: str) -> str:
    """'2026-10' -> '21 Sep - 20 Oct 2026'."""
    y, m = (int(x) for x in payroll_id.split("-"))
    py, pm = (y - 1, 12) if m == 1 else (y, m - 1)
    return f"21 {date(py, pm, 1).strftime('%b')} - 20 {date(y, m, 1).strftime('%b')} {y}"


# ── the day-by-day timesheet ("My day") ─────────────────────────────────────────────────────────────
# Stored values (the labels shown to the employee are friendlier: "Client site", "WFH", "Week off").
LOCATIONS = ("Office", "Client Site", "Work From Home", "Leave", "Week Off", "PHY")
DAY_OFF_LOCATIONS = ("Leave", "Week Off", "PHY")
TASK_STATUSES = ("done", "in_progress", "blocked")
DEADLINE_TIME = time(23, 59, 59)          # a sub-cycle closes at 23:59 IST on (end date + 5 days)
MIN_REMARKS_CHARS = 3


def typed_hours_ok(h) -> bool:
    """Hours an employee types: more than 0, at most 24, up to 2 decimals."""
    try:
        h = float(h)
    except (TypeError, ValueError):
        return False
    return 0 < h <= MAX_DAY_HOURS and round(h, 2) == h


def deadline_passed(cycle: "Cycle", now_ist: datetime) -> bool:
    """now_ist is a naive datetime in IST."""
    return now_ist > datetime.combine(cycle.deadline, DEADLINE_TIME)


def day_submit_errors(location: str, entries) -> list:
    """Strict check when an employee submits a day. A day off (Leave / Week off / PHY) needs no rows;
    a working day needs at least one, each with valid typed hours; the day's hours total at most 24; an
    unplanned row (not in Nexus Quant) needs a description. Returns human-readable problems."""
    if location in DAY_OFF_LOCATIONS:
        return [] if not entries else ["A day off carries no work rows - remove them or change the location"]
    if not entries:
        return ["Add at least one task for the day"]
    errors, total = [], 0.0
    for i, e in enumerate(entries, start=1):
        if not typed_hours_ok(e.get("hours")):
            errors.append(f"Row {i}: enter hours (more than 0 and at most {MAX_DAY_HOURS:g}, up to 2 decimals)")
        else:
            total += float(e["hours"])
        if e.get("is_unplanned") and len((e.get("remarks") or "").strip()) < MIN_REMARKS_CHARS:
            errors.append(f"Row {i}: describe the unplanned work")
    if round(total, 2) > MAX_DAY_HOURS:
        errors.append(f"The day's hours add up to {total:g} - more than {MAX_DAY_HOURS:g}")
    return errors
