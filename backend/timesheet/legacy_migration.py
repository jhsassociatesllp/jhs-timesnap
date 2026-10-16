# backend/timesheet/legacy_migration.py
"""
One-off conversion of legacy nested timesheets (Timesheet_data: payrolls[].entries[])
into the per-entry `timesheet_entries` shape. Never modifies or deletes the source.

Idempotent: each new document carries legacy_id (the old entry id, or a stable hash)
and is upserted on (employee_id, legacy_id), so re-running never duplicates.
Legacy rows have no task, so task_id is None, task_status is None and legacy=True.
"""
import hashlib
from datetime import date, datetime
from typing import Dict, Iterator

from backend.timesheet import rules


def _entries_of(payroll: dict) -> list:
    if "entries" in payroll:
        return payroll.get("entries") or []
    out = []
    for w in payroll.get("weeks", []) or []:          # oldest documents nest by week
        out.extend(w.get("entries", []) or [])
    return out


def _legacy_id(emp: str, e: dict, idx: int) -> str:
    if e.get("id"):
        return str(e["id"])
    raw = f"{emp}|{e.get('date')}|{e.get('projectCode')}|{e.get('activity')}|{idx}"
    return "h_" + hashlib.sha1(raw.encode()).hexdigest()[:20]


def convert(doc: dict) -> Iterator[dict]:
    """Yield new-shape entry dicts for one legacy employee document."""
    emp = str(doc.get("employeeId") or "").strip().upper()
    if not emp:
        return
    for payroll in doc.get("payrolls", []) or []:
        approved = payroll.get("approval_status") == "approved"
        for idx, e in enumerate(_entries_of(payroll)):
            try:
                d = date.fromisoformat(str(e.get("date") or "")[:10])
                hours = float(e.get("projectHours"))
            except (ValueError, TypeError):
                continue                                  # day-off rows etc. carry no hours
            if hours <= 0:
                continue
            now = datetime.utcnow()
            yield {
                "employee_id": emp, "date": d.isoformat(),
                "task_id": None, "task_name": "",
                "project_code": (e.get("projectCode") or "").strip(),
                "client": (e.get("client") or "").strip(),
                "project": (e.get("project") or "").strip(),
                "activity": (e.get("activity") or "").strip(),
                "hours": round(hours, 2), "task_status": None,
                "is_unplanned": False, "unplanned_reason": "", "awaiting_hrms": False,
                "cycle_id": rules.cycle_for(d).id,
                "approved": approved, "locked": False,
                "legacy": True, "legacy_id": _legacy_id(emp, e, idx),
                "created_at": now, "updated_at": now,
            }


def migrate(source, dest, apply: bool = False) -> Dict[str, int]:
    """Convert every legacy document in `source` into `dest`. Dry-run unless apply=True."""
    stats = {"employees": 0, "entries": 0, "inserted": 0, "already_present": 0}
    for doc in source.find({}):
        stats["employees"] += 1
        for new in convert(doc):
            stats["entries"] += 1
            key = {"employee_id": new["employee_id"], "legacy_id": new["legacy_id"]}
            if dest.count_documents(key, limit=1):
                stats["already_present"] += 1
                continue
            if apply:
                dest.update_one(key, {"$setOnInsert": new}, upsert=True)
            stats["inserted"] += 1
    return stats
