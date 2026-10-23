# backend/hrms/rules.py
"""Pure HRMS rules: Muster-code classification, punch hours and the reco outcome."""
from datetime import time
from typing import Dict, Optional

from backend.timesheet import rules as ts_rules

# Muster code -> kind. Overridable via config.hrms_status_codes (see router/reco).
#   working  : present (punch expected, reconcilable)   half_day: treated like working
#   off      : weekly off / public holiday / leave -> no timesheet expected
#   absent   : no attendance
DEFAULT_STATUS_CODES: Dict[str, str] = {
    "PST": "working", "HD": "working",
    "WEO": "weekly_off", "HOL": "holiday", "PHY": "holiday",
    "CL": "leave", "SL": "leave", "PL": "leave",
    "ABS": "absent",
}
OFF_KINDS = {"weekly_off", "holiday", "leave"}

FLAGGED_RESULTS = {"short", "over", "no_punch", "not_filled"}
RESULTS = ("matched", "short", "over", "no_punch", "not_filled", "leave")


def classify(code: str, mapping: Optional[Dict[str, str]] = None) -> str:
    """'unknown' for codes we have no mapping for (reported as a warning)."""
    code = (code or "").strip().upper()
    return (mapping or DEFAULT_STATUS_CODES).get(code, "unknown")


def seconds(t: time) -> int:
    return t.hour * 3600 + t.minute * 60 + t.second


OVERNIGHT_BEFORE_HOUR = 6          # an out punch before 06:00 that is earlier than the in punch is after midnight
MAX_GROSS_HOURS = 18.0


def gross_hours(t_in: Optional[time], t_out: Optional[time]) -> Optional[float]:
    """out - in in decimal hours. None if either punch is missing. An out punch shortly after midnight (before 06:00)
    that is earlier than the in punch is taken as the next morning. Raises ValueError for any other out-before-in and for
    more than 18 hours between the punches (never silently negative or absurd).
    NOTE: the HRMS 'Total Hours' column is hours.minutes, NOT decimal - never use it."""
    if t_in is None or t_out is None:
        return None
    diff = seconds(t_out) - seconds(t_in)
    if diff < 0:
        if t_out.hour >= OVERNIGHT_BEFORE_HOUR:
            raise ValueError("out time is before in time")
        diff += 24 * 3600
    if diff > MAX_GROSS_HOURS * 3600:
        raise ValueError("more than 18 hours between in and out - please check the punches")
    return round(diff / 3600.0, 2)


def net_from_gross(gross: Optional[float], lunch: float = ts_rules.LUNCH_HOURS) -> Optional[float]:
    return None if gross is None else ts_rules.net_hours(gross, lunch)


def reco_result(kind: str, entry_count: int, task_hours: float, net: Optional[float],
                tolerance: float = ts_rules.TOLERANCE_HOURS) -> Optional[str]:
    """Reconciliation outcome for one employee-day, or None when nothing is expected
    and nothing was filled (no row is written).
      off kind                          -> 'leave'   (no timesheet expected)
      working, no punch, entries        -> 'no_punch'
      working, no punch, no entries     -> None
      working, punch, no entries        -> 'not_filled'
      working, punch, entries           -> matched / short / over (|diff| <= tolerance)
      absent, entries                   -> 'no_punch'; absent, none -> None
      unknown kind                      -> None (flagged at upload time)"""
    if kind in OFF_KINDS:
        return "leave"
    if kind == "absent":
        return "no_punch" if entry_count else None
    if kind != "working":
        return None
    if net is None:
        return "no_punch" if entry_count else None
    if entry_count == 0:
        return "not_filled"
    diff = round(task_hours - net, 2)
    if abs(diff) <= tolerance:
        return "matched"
    return "short" if diff < 0 else "over"
