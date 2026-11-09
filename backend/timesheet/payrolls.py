# backend/timesheet/payrolls.py
"""
Payrolls and sub-cycles that an ADMIN created (Admin setup page) and the working rules the admin controls.

  * A payroll is named by the month it ENDS in ('2026-10' = 21 Sep - 20 Oct 2026) and holds three 10-day sub-cycles
    (21-end of the previous month, 1-10, 11-20). The dates follow the standard split, so entries keep their cycle ids;
    the admin controls which payrolls exist and each sub-cycle's DEADLINE (default: end date + `deadline_days`, 23:59 IST).
  * Only cycles that belong to an admin-created payroll are open for filling and appear in Review team.
  * Working rules (hours per day, week-off days, holidays, default deadline days) live in the `config` document.
"""
import time
from dataclasses import replace
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

from backend.cycle.store import store
from backend.timesheet import rules

CONFIG_ID = "timesheet"
DEFAULT_DEADLINE_DAYS = rules.FILL_DEADLINE_DAYS
_TTL = 5.0
_cache: Dict[int, tuple] = {}


def invalidate() -> None:
    _cache.clear()


def _all() -> List[dict]:
    key = id(store.payrolls)
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < _TTL:
        return hit[1]
    docs = list(store.payrolls.find({}).sort("_id", -1))
    _cache[key] = (time.monotonic(), docs)
    return docs


# ─────────────────────────────── settings ────────────────────────────────────

def settings_from(doc: Optional[dict]) -> dict:
    """Working rules from the config document, with safe defaults. Pure."""
    doc = doc or {}
    hol: Dict[date, str] = {}
    names = doc.get("holiday_names") or {}
    for h in doc.get("holidays", []) or []:
        try:
            d = date.fromisoformat(str(h)[:10])
        except ValueError:
            continue
        hol[d] = str(names.get(str(h)[:10]) or "")
    try:
        std = float(doc.get("standard_hours", rules.STANDARD_HOURS))
        if not 0 < std <= 24:
            std = rules.STANDARD_HOURS
    except (TypeError, ValueError):
        std = rules.STANDARD_HOURS
    off = tuple(sorted({int(x) for x in (doc.get("week_off_days") or rules.WEEK_OFF_DEFAULT)
                        if str(x).isdigit() and 0 <= int(x) <= 6}))
    try:
        dd = int(doc.get("deadline_days", DEFAULT_DEADLINE_DAYS))
        if not 0 <= dd <= 60:
            dd = DEFAULT_DEADLINE_DAYS
    except (TypeError, ValueError):
        dd = DEFAULT_DEADLINE_DAYS
    def _num(key, default, lo, hi):
        try:
            v = float(doc.get(key, default))
            return v if lo <= v <= hi else default
        except (TypeError, ValueError):
            return default

    return {"standard_hours": std, "week_off": off if 0 < len(off) < 7 else rules.WEEK_OFF_DEFAULT,
            "deadline_days": dd, "holidays": hol,
            "lunch_hours": _num("lunch_hours", rules.LUNCH_HOURS, 0.0, 3.0),            # taken off HRMS gross hours
            "tolerance_hours": _num("tolerance_hours", rules.TOLERANCE_HOURS, 0.0, 4.0)}  # typed vs HRMS counts as matched within this


def settings() -> dict:
    return settings_from(store.config.find_one({"_id": CONFIG_ID}))


# ─────────────────────────────── payrolls ────────────────────────────────────

def build_payroll(payroll_id: str, deadline_days: int = DEFAULT_DEADLINE_DAYS, created_by: str = "") -> dict:
    """The document for payroll '2026-10': its three standard sub-cycles with default deadlines."""
    y, m = (int(x) for x in payroll_id.split("-"))
    py, pm = (y - 1, 12) if m == 1 else (y, m - 1)
    cycles = []
    for d in (date(py, pm, 21), date(y, m, 1), date(y, m, 11)):
        c = rules.cycle_for(d)
        cycles.append({"id": c.id, "label": c.label, "start": c.start.isoformat(), "end": c.end.isoformat(),
                       "deadline": (c.end + timedelta(days=deadline_days)).isoformat()})
    return {"_id": payroll_id, "label": rules.payroll_label(payroll_id), "start": cycles[0]["start"], "end": cycles[2]["end"],
            "cycles": cycles, "created_by": created_by, "created_at": datetime.utcnow()}


def list_payrolls() -> List[dict]:
    return _all()


def payroll_of_cycle(cycle_id: str) -> Optional[dict]:
    try:
        pid = rules.payroll_id_for_cycle(cycle_id)
    except ValueError:
        return None
    return next((p for p in _all() if p["_id"] == pid), None)


def cycle_config(cycle_id: str) -> Optional[dict]:
    p = payroll_of_cycle(cycle_id)
    return next((c for c in (p or {}).get("cycles", []) if c["id"] == cycle_id), None)


def is_configured(cycle_id: str) -> bool:
    return cycle_config(cycle_id) is not None


def effective_cycle(d: date) -> rules.Cycle:
    """The standard cycle for a date, with the ADMIN's deadline when its payroll has been created."""
    cyc = rules.cycle_for(d)
    conf = cycle_config(cyc.id)
    if conf:
        return replace(cyc, deadline=date.fromisoformat(conf["deadline"]))
    return cyc


def effective_cycle_by_id(cycle_id: str) -> rules.Cycle:
    cyc = rules.cycle_from_id(cycle_id)
    conf = cycle_config(cycle_id)
    return replace(cyc, deadline=date.fromisoformat(conf["deadline"])) if conf else cyc
