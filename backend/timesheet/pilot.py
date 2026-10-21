# backend/timesheet/pilot.py
"""
Who sees the new day-by-day timesheet ("My day") at /timesheet. Everyone else keeps the classic timesheet.

  python -m backend.timesheet.pilot list
  python -m backend.timesheet.pilot add JHS1234 JHS5678
  python -m backend.timesheet.pilot remove JHS1234

It edits config.pilot_employees in the database your .env points at. Put a few employees AND their reporting
manager in the pilot, and start at the beginning of a 10-day sub-cycle (1st, 11th or 21st).
"""
import re
import sys
from typing import List

from backend.cycle.store import CONFIG_ID, store

CODE_RE = re.compile(r"^[A-Z0-9_-]{2,20}$")


def _codes(raw: List[str]) -> List[str]:
    out = []
    for c in raw:
        c = c.strip().upper()
        if not CODE_RE.match(c):
            raise ValueError(f"not a valid employee code: {c!r}")
        out.append(c)
    return out


def current() -> List[str]:
    doc = store.config.find_one({"_id": CONFIG_ID}) or {}
    return sorted({str(e).strip().upper() for e in doc.get("pilot_employees", []) or []})


def add(codes: List[str]) -> List[str]:
    store.config.update_one({"_id": CONFIG_ID}, {"$addToSet": {"pilot_employees": {"$each": _codes(codes)}}}, upsert=True)
    return current()


def remove(codes: List[str]) -> List[str]:
    store.config.update_one({"_id": CONFIG_ID}, {"$pull": {"pilot_employees": {"$in": _codes(codes)}}})
    return current()


def main(argv: List[str]) -> int:
    if not argv or argv[0] not in ("list", "add", "remove") or (argv[0] != "list" and len(argv) < 2):
        print(__doc__)
        return 2
    try:
        result = {"list": lambda: current(), "add": lambda: add(argv[1:]), "remove": lambda: remove(argv[1:])}[argv[0]]()
    except ValueError as e:
        print(e, file=sys.stderr)
        return 2
    print("pilot employees:", ", ".join(result) or "(none)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
