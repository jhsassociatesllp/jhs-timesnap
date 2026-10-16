# backend/timesheet/daily.py
"""
Hours-only daily timesheet (pilot), running ALONGSIDE the legacy payroll-cycle grid.

  * Own data only: every endpoint requires current_user == employee_id (403 otherwise).
  * Only employees listed in config.pilot_employees may use it; the free-text
    employees (partner JHS01, JHS1562) stay on the legacy grid.
  * Projects/tasks come from Nexus Quant (read-only). client / project / project code
    are copied from NQ on the SERVER; whatever the browser sends for them is ignored.
  * Storage: timesheet_entries (one doc per entry) and day_submissions. The legacy
    Timesheet_data / Timesheet_temp collections are never touched.
"""
from datetime import date, datetime
from typing import List, Literal, Optional

import pytz
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.auth import get_current_user
from backend.database import (
    config_collection,
    day_submissions_collection,
    employee_details_collection,
    hrms_attendance_collection,
    timesheet_entries_collection,
)
from backend.nq import cache as nq_cache
from backend.nq import repository as nq_repo
from backend.nq.models import NQUnavailable
from backend.timesheet import rules
from backend.timesheet.router import _is_free_text_employee

router = APIRouter(prefix="/timesheet/v2", tags=["Timesheet daily"])
IST = pytz.timezone("Asia/Kolkata")
CONFIG_ID = "timesheet"
MAX_ENTRIES_PER_DAY = 20


class _Store:
    """Collection handles in one place so tests can point them at a scratch database."""
    entries = timesheet_entries_collection
    submissions = day_submissions_collection
    hrms = hrms_attendance_collection
    config = config_collection
    employees = employee_details_collection


store = _Store()


# ─────────────────────────────── models ──────────────────────────────────────

class EntryIn(BaseModel):
    task_id: Optional[int] = None
    activity: str = Field(..., max_length=1000)
    hours: Optional[float] = None
    task_status: Literal["done", "in_progress", "blocked"]
    is_unplanned: bool = False
    unplanned_reason: str = Field("", max_length=500)
    project_code: Optional[str] = Field(None, max_length=30)  # unplanned only; validated against NQ


class DayIn(BaseModel):
    entries: List[EntryIn]


class SubmitIn(BaseModel):
    reco_reason: str = Field("", max_length=500)


# ─────────────────────────────── helpers ─────────────────────────────────────

def get_config() -> dict:
    doc = store.config.find_one({"_id": CONFIG_ID}) or {}
    holidays = set()
    for h in doc.get("holidays", []) or []:
        try:
            holidays.add(date.fromisoformat(str(h)[:10]))
        except ValueError:
            continue
    return {
        "standard_hours": float(doc.get("standard_hours", rules.STANDARD_HOURS)),
        "lunch_hours": float(doc.get("lunch_hours", rules.LUNCH_HOURS)),
        "tolerance": float(doc.get("tolerance", rules.TOLERANCE_HOURS)),
        "pilot_employees": {str(e).strip().upper() for e in doc.get("pilot_employees", []) or []},
        "holidays": holidays,
    }


def _require_self(employee_id: str, current_user: str) -> str:
    emp = (employee_id or "").strip().upper()
    if emp != (current_user or "").strip().upper():
        raise HTTPException(403, "Unauthorized")
    return emp


def _is_enabled(emp: str, cfg: dict) -> bool:
    if emp not in cfg["pilot_employees"]:
        return False
    doc = store.employees.find_one({"EmpID": emp}, {"PartnerEmpCode": 1}) or {}
    return not _is_free_text_employee(emp, (doc.get("PartnerEmpCode") or ""))


def _require_enabled(emp: str, cfg: dict) -> None:
    if not _is_enabled(emp, cfg):
        raise HTTPException(403, "The daily timesheet is not enabled for you")


def _parse_date(value: str, allow_future: bool = False) -> date:
    try:
        d = date.fromisoformat(value)
    except ValueError:
        raise HTTPException(400, "date must be YYYY-MM-DD")
    if not allow_future and d > datetime.now(IST).date():
        raise HTTPException(400, "Cannot fill a future date")
    return d


def _hrms_for(emp: str, d: date) -> Optional[dict]:
    """HRMS strip for the day, or None if not uploaded (or the day is leave)."""
    doc = store.hrms.find_one({"employee_id": emp, "date": d.isoformat()})
    return doc or None


def _my_tasks(emp: str, d: date):
    """(tasks, nq_unavailable). Never raises for an NQ outage."""
    try:
        return nq_repo.get_tasks_for_employee(emp, d), False
    except NQUnavailable:
        return [], True


def _hours_used(emp: str, task_ids: List[int]) -> dict:
    if not task_ids:
        return {}
    pipeline = [
        {"$match": {"employee_id": emp, "task_id": {"$in": task_ids}, "hours": {"$ne": None}}},
        {"$group": {"_id": "$task_id", "h": {"$sum": "$hours"}}},
    ]
    return {r["_id"]: round(r["h"], 2) for r in store.entries.aggregate(pipeline)}


def _task_view(t, used: dict, holidays) -> dict:
    return {
        "task_id": t.id, "task_name": t.name, "parent_task_id": t.parent_task_id,
        "project_code": t.project_code, "project_name": t.project_name,
        "client_name": t.client_name, "start_date": t.start_date, "end_date": t.end_date,
        "status": t.status, "is_overdue": t.is_overdue,
        "hours_used": used.get(t.id, 0.0),
        # NQ has no allocation % column -> 100% assumed (flagged in the response).
        "budget_hours": rules.budget_hours(t.start_date, t.end_date, holidays),
    }


def _entry_view(e: dict) -> dict:
    return {k: e.get(k) for k in (
        "task_id", "task_name", "project_code", "client", "project", "activity", "hours",
        "task_status", "is_unplanned", "unplanned_reason", "awaiting_hrms", "locked")}


def _totals(entries: List[dict], hrms_net: Optional[float], tolerance: float) -> dict:
    task_hours = round(sum(e["hours"] for e in entries if e.get("hours") is not None), 2)
    awaiting = any(e.get("awaiting_hrms") for e in entries)
    if hrms_net is None or awaiting or not entries:
        return {"task_hours": task_hours, "hrms_net": hrms_net, "difference": None,
                "within_tolerance": None, "awaiting_hrms": awaiting,
                "reason_required": False}
    ok = rules.within_tolerance(task_hours, hrms_net, tolerance)
    return {"task_hours": task_hours, "hrms_net": hrms_net,
            "difference": rules.difference(task_hours, hrms_net),
            "within_tolerance": ok, "awaiting_hrms": False, "reason_required": not ok}


def _day_payload(emp: str, d: date, cfg: dict) -> dict:
    tasks, nq_down = _my_tasks(emp, d)
    used = _hours_used(emp, [t.id for t in tasks])
    entries = list(store.entries.find({"employee_id": emp, "date": d.isoformat()}).sort("created_at", 1))
    hrms = _hrms_for(emp, d)
    is_leave = bool(hrms and hrms.get("leave_flag"))
    net = None if (not hrms or is_leave or hrms.get("net_hours") is None) else float(hrms["net_hours"])
    sub = store.submissions.find_one({"employee_id": emp, "date": d.isoformat()})
    cyc = rules.cycle_for(d)
    return {
        "date": d.isoformat(),
        "cycle": {"id": cyc.id, "label": cyc.label, "start": cyc.start, "end": cyc.end,
                  "deadline": cyc.deadline},
        "hrms": None if not hrms else {
            "in_time": hrms.get("in_time"), "out_time": hrms.get("out_time"),
            "gross": hrms.get("gross_hours"), "lunch": cfg["lunch_hours"], "net": net,
            "is_leave": is_leave},
        "tasks": [_task_view(t, used, cfg["holidays"]) for t in tasks],
        "allocation_assumed_100": True,
        "entries": [_entry_view(e) for e in entries],
        "totals": _totals(entries, net, cfg["tolerance"]),
        "submitted": bool(sub), "submitted_at": sub.get("submitted_at") if sub else None,
        "reco_reason": sub.get("reco_reason", "") if sub else "",
        "locked": any(e.get("locked") for e in entries),
        "nq_unavailable": nq_down,
        "nq_data_may_be_stale": nq_down or nq_cache.data_may_be_stale(),
    }


def _build_entry_docs(emp: str, d: date, body: DayIn, cfg: dict) -> List[dict]:
    """Validate the payload and turn it into entry documents. Client/project/code
    come from NQ, hours for a one-entry day from HRMS. Raises HTTPException."""
    if not body.entries:
        raise HTTPException(422, "Add at least one entry")
    if len(body.entries) > MAX_ENTRIES_PER_DAY:
        raise HTTPException(422, f"At most {MAX_ENTRIES_PER_DAY} entries per day")

    tasks, nq_down = _my_tasks(emp, d)
    needs_nq = any((not e.is_unplanned) or e.project_code for e in body.entries)
    if nq_down and needs_nq:
        raise HTTPException(503, "Project data is unavailable right now — please try again shortly")
    by_id = {t.id: t for t in tasks}

    hrms = _hrms_for(emp, d)
    net = None
    if hrms and not hrms.get("leave_flag") and hrms.get("net_hours") is not None:
        net = float(hrms["net_hours"])
    auto_hours, locked_hours, awaiting = rules.one_task_hours(len(body.entries), net)

    cyc = rules.cycle_for(d)
    now = datetime.utcnow()
    seen_tasks = set()
    docs = []
    for i, e in enumerate(body.entries, start=1):
        row = f"Entry {i}"
        activity = (e.activity or "").strip()
        if not activity:
            raise HTTPException(422, f"{row}: describe what you did")
        base = {
            "employee_id": emp, "date": d.isoformat(), "activity": activity,
            "task_status": e.task_status, "cycle_id": cyc.id,
            "approved": False, "locked": False, "created_at": now, "updated_at": now,
        }
        if e.is_unplanned:
            reason = (e.unplanned_reason or "").strip()
            if not reason:
                raise HTTPException(422, f"{row}: unplanned work needs a reason")
            if e.task_id is not None:
                raise HTTPException(422, f"{row}: an unplanned entry cannot have a task")
            proj = None
            if e.project_code:
                try:
                    proj = nq_repo.get_project(e.project_code.strip())
                except NQUnavailable:
                    raise HTTPException(503, "Project data is unavailable right now — please try again shortly")
                if proj is None:
                    raise HTTPException(422, f"{row}: unknown project code")
            base.update({
                "task_id": None, "task_name": "", "is_unplanned": True, "unplanned_reason": reason,
                "project_code": proj.project_code if proj else "",
                "client": proj.client_name if proj else "",
                "project": proj.project_name if proj else "",
            })
        else:
            t = by_id.get(e.task_id)
            if t is None:
                raise HTTPException(422, f"{row}: task is not assigned to you for {d.isoformat()}")
            if t.id in seen_tasks:
                raise HTTPException(422, f"{row}: task listed twice — combine into one entry")
            seen_tasks.add(t.id)
            base.update({
                "task_id": t.id, "task_name": t.name, "is_unplanned": False, "unplanned_reason": "",
                "project_code": t.project_code, "client": t.client_name, "project": t.project_name,
            })
        if locked_hours:                      # one entry: hours are HRMS net, never the browser's
            base["hours"], base["awaiting_hrms"] = auto_hours, awaiting
        else:
            if not rules.valid_hours(e.hours):
                raise HTTPException(422, f"{row}: hours must be between 0.25 and 24 in steps of 0.25")
            base["hours"], base["awaiting_hrms"] = round(float(e.hours), 2), False
        docs.append(base)
    return docs


def _assert_not_locked(emp: str, d: date) -> None:
    if store.entries.find_one({"employee_id": emp, "date": d.isoformat(), "locked": True}):
        raise HTTPException(409, "This day is locked and can no longer be edited")


# ─────────────────────────────── routes ──────────────────────────────────────

@router.get("/enabled/{employee_id}")
def daily_enabled(employee_id: str, current_user: str = Depends(get_current_user)):
    emp = _require_self(employee_id, current_user)
    return {"enabled": _is_enabled(emp, get_config())}


@router.get("/day/{employee_id}")
def get_day(employee_id: str, date: str, current_user: str = Depends(get_current_user)):
    emp = _require_self(employee_id, current_user)
    cfg = get_config()
    _require_enabled(emp, cfg)
    return _day_payload(emp, _parse_date(date), cfg)


@router.put("/day/{employee_id}/{date}")
def save_day(employee_id: str, date: str, body: DayIn, current_user: str = Depends(get_current_user)):
    """Replace the day's entries (draft). Editing a submitted day withdraws the
    submission - the employee must submit again."""
    emp = _require_self(employee_id, current_user)
    cfg = get_config()
    _require_enabled(emp, cfg)
    d = _parse_date(date)
    _assert_not_locked(emp, d)
    docs = _build_entry_docs(emp, d, body, cfg)
    iso = d.isoformat()
    old = store.entries.find_one({"employee_id": emp, "date": iso}, {"created_at": 1}, sort=[("created_at", 1)])
    if old and old.get("created_at"):
        for doc in docs:
            doc["created_at"] = old["created_at"]
    store.entries.delete_many({"employee_id": emp, "date": iso})
    store.entries.insert_many(docs)
    store.submissions.delete_one({"employee_id": emp, "date": iso})
    return _day_payload(emp, d, cfg)


@router.post("/day/{employee_id}/{date}/submit")
def submit_day(employee_id: str, date: str, body: SubmitIn, current_user: str = Depends(get_current_user)):
    emp = _require_self(employee_id, current_user)
    cfg = get_config()
    _require_enabled(emp, cfg)
    d = _parse_date(date)
    iso = d.isoformat()
    _assert_not_locked(emp, d)
    entries = list(store.entries.find({"employee_id": emp, "date": iso}))
    if not entries:
        raise HTTPException(422, "Nothing to submit — save at least one entry first")

    payload = _day_payload(emp, d, cfg)
    totals = payload["totals"]
    reason = (body.reco_reason or "").strip()
    if totals["reason_required"] and not reason:
        raise HTTPException(
            422, f"Task hours ({totals['task_hours']}) differ from HRMS net hours "
                 f"({totals['hrms_net']}) by more than {cfg['tolerance']} h — give a reason")
    if not totals["reason_required"]:
        reason = ""
    now = datetime.utcnow()
    store.submissions.update_one(
        {"employee_id": emp, "date": iso},
        {"$set": {"employee_id": emp, "date": iso, "submitted_at": now,
                  "reco_reason": reason, "cycle_id": rules.cycle_for(d).id}},
        upsert=True,
    )
    return _day_payload(emp, d, cfg)
