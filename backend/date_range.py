# backend/date_range.py
"""
Date-range filter shared by the HR / admin lists and their Excel / Word / PDF downloads (for analysis).

HR picks "From" and "To" as calendar days (YYYY-MM-DD) in India time (IST). Stored timestamps are UTC, so the
range is converted once: From = 00:00 IST of that day, To = the end of that day in IST (both inclusive).
Either side may be left empty (open-ended).
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException

IST = timedelta(hours=5, minutes=30)


def bounds(date_from: Optional[str], date_to: Optional[str]):
    """-> (lo, hi) as naive UTC datetimes, or None for an open side. lo is inclusive, hi is exclusive."""
    def day(s):
        try:
            return datetime.strptime(s.strip(), "%Y-%m-%d")
        except Exception:
            raise HTTPException(400, f"Date '{s}' is not valid. Use YYYY-MM-DD.")
    lo = day(date_from) - IST if date_from else None
    hi = day(date_to) + timedelta(days=1) - IST if date_to else None
    if lo and hi and lo >= hi:
        raise HTTPException(400, "'From' date is after the 'To' date.")
    return lo, hi


def within(value, lo, hi) -> bool:
    """True if `value` (datetime, ISO string or None) falls in [lo, hi). No range -> everything matches;
    a range -> a row without that date does not match."""
    if lo is None and hi is None:
        return True
    if value is None or value == "":
        return False
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except Exception:
            return False
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return (lo is None or value >= lo) and (hi is None or value < hi)
