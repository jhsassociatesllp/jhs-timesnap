# backend/timesheet/pilot.py
"""
Who sees the new day-by-day timesheet ("My day") at /timesheet.

By default EVERY employee does (free-text employees keep the classic grid). To stage a roll-out, switch to
pilot mode: only the listed codes see it and everyone else keeps the classic timesheet.

  python -m backend.timesheet.pilot scope pilot     # or: scope all
  python -m backend.timesheet.pilot include JHS1191   # free-text employee (partner JHS01) who should see My day
  python -m backend.timesheet.pilot uninclude JHS1191
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


def current_include() -> List[str]:
    doc = store.config.find_one({"_id": CONFIG_ID}) or {}
    return sorted({str(e).strip().upper() for e in doc.get("new_timesheet_include", []) or []})


def include(codes: List[str]) -> List[str]:
    store.config.update_one({"_id": CONFIG_ID}, {"$addToSet": {"new_timesheet_include": {"$each": _codes(codes)}}}, upsert=True)
    return current_include()


def uninclude(codes: List[str]) -> List[str]:
    store.config.update_one({"_id": CONFIG_ID}, {"$pull": {"new_timesheet_include": {"$in": _codes(codes)}}})
    return current_include()


def set_scope(value: str) -> str:
    value = value.strip().lower()
    if value not in ("all", "pilot"):
        raise ValueError("scope must be 'all' or 'pilot'")
    store.config.update_one({"_id": CONFIG_ID}, {"$set": {"timesheet_scope": value}}, upsert=True)
    return value


def main(argv: List[str]) -> int:
    if argv and argv[0] == "scope" and len(argv) == 2:
        try:
            print("timesheet scope:", set_scope(argv[1]))
            return 0
        except ValueError as e:
            print(e, file=sys.stderr)
            return 2
    if argv and argv[0] in ("include", "uninclude") and len(argv) >= 2:
        try:
            result = (include if argv[0] == "include" else uninclude)(argv[1:])
        except ValueError as e:
            print(e, file=sys.stderr)
            return 2
        print("always on the new timesheet (even if free-text):", ", ".join(result) or "(none)")
        return 0
    if not argv or argv[0] not in ("list", "add", "remove") or (argv[0] != "list" and len(argv) < 2):
        print(__doc__)
        return 2
    try:
        result = {"list": lambda: current(), "add": lambda: add(argv[1:]), "remove": lambda: remove(argv[1:])}[argv[0]]()
    except ValueError as e:
        print(e, file=sys.stderr)
        return 2
    print("pilot employees:", ", ".join(result) or "(none)")
    if argv[0] == "list":
        print("always on the new timesheet (even if free-text):", ", ".join(current_include()) or "(none)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
