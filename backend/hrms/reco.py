# backend/hrms/reco.py
"""
Reconciliation of timesheet hours against HRMS net hours, per employee per day.
Runs after every HRMS import and whenever a pilot employee saves/submits a day.
Only PILOT employees (config.pilot_employees) are reconciled - everyone else is still
on the legacy grid, so reconciling them would just show "not filled".
"""
import logging
from datetime import datetime
from typing import Dict, Iterable, List, Optional

from backend.database import (
    config_collection,
    daily_reco_collection,
    day_submissions_collection,
    employee_details_collection,
    hrms_attendance_collection,
    hrms_uploads_collection,
    timesheet_entries_collection,
)
from backend.hrms import rules
from backend.timesheet import rules as ts_rules

log = logging.getLogger("hrms")
CONFIG_ID = "timesheet"


class _Store:
    """Collection handles in one place so tests can point them at a scratch database."""
    entries = timesheet_entries_collection
    submissions = day_submissions_collection
    hrms = hrms_attendance_collection
    uploads = hrms_uploads_collection
    reco = daily_reco_collection
    config = config_collection
    employees = employee_details_collection


store = _Store()


def config() -> dict:
    doc = store.config.find_one({"_id": CONFIG_ID}) or {}
    codes = dict(rules.DEFAULT_STATUS_CODES)
    codes.update({str(k).strip().upper(): str(v) for k, v in (doc.get("hrms_status_codes") or {}).items()})
    return {
        "tolerance": float(doc.get("tolerance", ts_rules.TOLERANCE_HOURS)),
        "pilot": {str(e).strip().upper() for e in doc.get("pilot_employees", []) or []},
        "status_codes": codes,
    }


def ensure_indexes() -> None:
    store.hrms.create_index([("employee_id", 1), ("date", 1)], unique=True)
    store.reco.create_index([("employee_id", 1), ("date", 1)], unique=True)
    store.reco.create_index([("date", 1), ("result", 1)])


def _entries_summary(emp: str, iso: str):
    rows = list(store.entries.find({"employee_id": emp, "date": iso}, {"hours": 1}))
    return len(rows), round(sum(r["hours"] for r in rows if r.get("hours") is not None), 2)


def recompute_day(emp: str, iso: str, reset_review: bool = False, cfg: Optional[dict] = None) -> Optional[str]:
    """Recompute and store the reco row for one employee-day. Returns the result
    (None if nothing is expected - any old row is then removed)."""
    cfg = cfg or config()
    emp = emp.strip().upper()
    if emp not in cfg["pilot"]:
        return None
    h = store.hrms.find_one({"employee_id": emp, "date": iso})
    if not h:
        return None                              # no HRMS data for the day: stays "awaiting HRMS"
    n, hours = _entries_summary(emp, iso)
    net = h.get("net_hours")
    result = rules.reco_result(h.get("kind") or rules.classify(h.get("status_code"), cfg["status_codes"]),
                               n, hours, net, cfg["tolerance"])
    key = {"employee_id": emp, "date": iso}
    if result is None:
        store.reco.delete_one(key)
        return None
    sub = store.submissions.find_one(key)
    now = datetime.utcnow()
    update = {
        "$set": {"hrms_net": net, "timesheet_hours": hours, "entry_count": n,
                 "diff": None if net is None else round(hours - net, 2),
                 "result": result, "reason": (sub or {}).get("reco_reason", ""),
                 "status_code": h.get("status_code"), "updated_at": now},
        "$setOnInsert": {"status": "open", "manager_note": ""},
    }
    if reset_review:
        update["$set"]["status"] = "open"
        update["$setOnInsert"].pop("status")
    store.reco.update_one(key, update, upsert=True)
    return result


def autofill_one_task_days(emp_ids: Iterable[str], date_from: str, date_to: str) -> int:
    """One entry that day => hours are HRMS net. Fills 'awaiting HRMS' rows and corrects
    rows after a re-upload. Skips locked/approved days and migrated legacy rows."""
    changed = 0
    ids = list(emp_ids)
    if not ids:
        return 0
    for h in store.hrms.find({"employee_id": {"$in": ids}, "date": {"$gte": date_from, "$lte": date_to},
                              "net_hours": {"$ne": None}, "leave_flag": {"$ne": True}}):
        rows = list(store.entries.find({"employee_id": h["employee_id"], "date": h["date"]}))
        if len(rows) != 1:
            continue
        r = rows[0]
        if r.get("locked") or r.get("approved") or r.get("legacy"):
            continue
        if r.get("hours") != h["net_hours"] or r.get("awaiting_hrms"):
            store.entries.update_one({"_id": r["_id"]}, {"$set": {
                "hours": h["net_hours"], "awaiting_hrms": False, "updated_at": datetime.utcnow()}})
            changed += 1
    return changed


def recompute_range(date_from: str, date_to: str) -> Dict[str, int]:
    """Autofill then reconcile every pilot employee's HRMS rows in the date range."""
    cfg = config()
    changed = autofill_one_task_days(cfg["pilot"], date_from, date_to)
    counts: Dict[str, int] = {}
    if cfg["pilot"]:
        for h in store.hrms.find({"employee_id": {"$in": list(cfg["pilot"])},
                                  "date": {"$gte": date_from, "$lte": date_to}}, {"employee_id": 1, "date": 1}):
            res = recompute_day(h["employee_id"], h["date"], cfg=cfg)
            if res:
                counts[res] = counts.get(res, 0) + 1
    counts["_autofilled"] = changed
    return counts


def safe_recompute_day(emp: str, iso: str) -> None:
    """Hook for the employee-facing endpoints: an employee edit re-opens any review.
    Never lets a reco problem break saving a timesheet."""
    try:
        recompute_day(emp, iso, reset_review=True)
    except Exception:
        log.exception("reco recompute failed for %s %s", emp, iso)


def reco_for_day(emp: str, iso: str) -> Optional[dict]:
    doc = store.reco.find_one({"employee_id": emp, "date": iso})
    if not doc:
        return None
    return {"result": doc.get("result"), "status": doc.get("status", "open"),
            "manager_note": doc.get("manager_note", ""), "diff": doc.get("diff")}
