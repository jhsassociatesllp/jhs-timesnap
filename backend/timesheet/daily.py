# backend/timesheet/daily.py
"""
"My day": the day-by-day timesheet.

  * Own data only: every endpoint requires current_user == employee_id (403 otherwise).
  * Only employees listed in config.pilot_employees use it; the free-text employees (partner JHS01,
    JHS1562) stay on the classic timesheet.
  * Tasks come from Nexus Quant (read-only): the employee picks an ASSIGNED task and client / project /
    project code are copied from NQ on the SERVER (whatever the browser sends for them is ignored).
    Work that is not in NQ is "Unplanned": it needs a description, which the manager reviews.
  * Hours are TYPED by the employee. HRMS is compared later (reconciliation) and never changes them.
  * Location is chosen per DAY (Office, Client Site, Work From Home, Leave, Week Off, PHY). A day off needs no rows.
  * Saving is a lenient DRAFT (autosave); "submit" is the strict check. Editing a submitted day withdraws the
    submission until it is submitted again. A day is read-only once its cycle is approved / locked, after the
    sub-cycle deadline (end date + 5 days, 23:59 IST), or if it was filled in the classic timesheet.
  * Storage: timesheet_entries (one document per row), day_submissions (submitted days only), day_drafts
    (location / saved state). The classic Timesheet_data is never touched here.
"""
from datetime import date, datetime, timedelta
from typing import List, Literal, Optional

import pytz
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from backend import indexes
from backend.auth import get_current_user
from backend.cycle.locks import cycle_review
from backend.database import (
    config_collection,
    day_drafts_collection,
    day_submissions_collection,
    employee_details_collection,
    timesheet_entries_collection,
)
from backend.hrms import reco as hrms_reco
from backend.nq import cache as nq_cache
from backend.nq import repository as nq_repo
from backend.nq.models import NQUnavailable
from backend.timesheet import payrolls, rules, scope
from backend.timesheet.router import _is_free_text_employee

router = APIRouter(prefix="/timesheet/v2", tags=["Timesheet day"])
IST = pytz.timezone("Asia/Kolkata")
CONFIG_ID = "timesheet"
MAX_ENTRIES_PER_DAY = 20


class _Store:
    """Collection handles in one place so tests can point them at a scratch database."""
    entries = timesheet_entries_collection
    submissions = day_submissions_collection
    drafts = day_drafts_collection
    config = config_collection
    employees = employee_details_collection


store = _Store()


# ─────────────────────────────── models ──────────────────────────────────────

class EntryIn(BaseModel):
    task_id: Optional[int] = None                       # an NQ task assigned to the employee, or None when unplanned
    hours: Optional[float] = None                       # may be empty while drafting; required at submit
    task_status: Literal["done", "in_progress", "blocked"] = "in_progress"
    remarks: str = Field("", max_length=1000)           # "what I did" (stored as `remarks`); required for unplanned work
    extra_remarks: str = Field("", max_length=1000)     # the optional "Remarks" box that follows it
    is_unplanned: bool = False


class DayIn(BaseModel):
    location: str = Field(..., max_length=30)
    entries: List[EntryIn] = []


# ─────────────────────────────── helpers ─────────────────────────────────────

def _now_ist() -> datetime:
    """Naive datetime in IST (tests replace this to pin the clock)."""
    return datetime.now(IST).replace(tzinfo=None)


def _today() -> date:
    return _now_ist().date()


def get_config() -> dict:
    doc = store.config.find_one({"_id": CONFIG_ID}) or {}
    st = payrolls.settings_from(doc)
    return {"pilot_employees": scope.pilot_codes(doc), "pilot_only": scope.pilot_only(doc),
            "include": scope.include_codes(doc), "holidays": set(st["holidays"]),
            "standard_hours": st["standard_hours"], "week_off": st["week_off"]}


def _require_self(employee_id: str, current_user: str) -> str:
    emp = (employee_id or "").strip().upper()
    if emp != (current_user or "").strip().upper():
        raise HTTPException(403, "Unauthorized")
    return emp


def _is_enabled(emp: str, cfg: dict) -> bool:
    if cfg["pilot_only"] and emp not in cfg["pilot_employees"]:
        return False
    if emp in cfg["include"]:                       # named employees use it even if they are free-text
        return True
    doc = store.employees.find_one({"EmpID": emp}, {"PartnerEmpCode": 1}) or {}
    return not _is_free_text_employee(emp, (doc.get("PartnerEmpCode") or ""))


def _require_enabled(emp: str, cfg: dict) -> None:
    if not _is_enabled(emp, cfg):
        raise HTTPException(403, "The new timesheet is not enabled for you")


def _parse_date(value: str, allow_future: bool = False) -> date:
    try:
        d = date.fromisoformat(value)
    except ValueError:
        raise HTTPException(400, "date must be YYYY-MM-DD")
    if not allow_future and d > _today():
        raise HTTPException(400, "Cannot fill a future date")
    return d


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


def _task_view(t, used: dict, cfg: dict) -> dict:
    return {
        "task_id": t.id, "task_name": t.name, "parent_task_id": t.parent_task_id,
        "project_code": t.project_code, "project_name": t.project_name,
        "client_name": t.client_name, "start_date": t.start_date, "end_date": t.end_date,
        "status": t.status, "is_overdue": t.is_overdue,
        "hours_used": used.get(t.id, 0.0),
        # NQ has no allocation % column -> 100% assumed
        "budget_hours": rules.budget_hours(t.start_date, t.end_date, cfg["holidays"], standard_hours=cfg["standard_hours"],
                                           week_off=cfg["week_off"]),
    }


def _entry_view(e: dict) -> dict:
    return {k: e.get(k) for k in ("task_id", "task_name", "client", "project", "project_code", "remarks", "extra_remarks",
                                  "hours", "task_status", "is_unplanned", "legacy")}


def _cycle_view(cyc: rules.Cycle, emp: Optional[str] = None, review: Optional[dict] = None) -> dict:
    view = {"id": cyc.id, "label": cyc.label, "start": cyc.start, "end": cyc.end, "deadline": cyc.deadline,
            "deadline_passed": rules.deadline_passed(cyc, _now_ist()), "configured": payrolls.is_configured(cyc.id)}
    if emp:                                   # manager review state of THIS employee's cycle
        rev = review if review is not None else (cycle_review(emp, cyc.id) or {})
        view["review_status"] = rev.get("status", "pending")
        view["review_note"] = rev.get("note") if rev.get("status") == "sent_back" else None
    return view


def _read_only_reason(emp: str, d: date, review: Optional[dict] = None, entries: Optional[List[dict]] = None,
                      sub: Optional[dict] = None, cyc: Optional[rules.Cycle] = None) -> Optional[str]:
    """Why this day cannot be edited, or None. `review` / `entries` / `sub` may be passed when the caller already
    has them (saves database round trips); otherwise they are looked up.
    A SUBMITTED day is locked for the employee: only an admin's "Allow changes" (sub["reopened"]) or the manager sending
    the cycle back opens it again."""
    iso = d.isoformat()
    if entries is None:
        if store.entries.find_one({"employee_id": emp, "date": iso, "legacy": True}, {"_id": 1}):
            return "classic"
        if store.entries.find_one({"employee_id": emp, "date": iso, "$or": [{"locked": True}, {"approved": True}]}, {"_id": 1}):
            return "approved"
    else:
        if any(e.get("legacy") for e in entries):
            return "classic"
        if any(e.get("locked") or e.get("approved") for e in entries):
            return "approved"
    cyc = cyc or payrolls.effective_cycle(d)
    if not payrolls.is_configured(cyc.id):
        return "no_cycle"
    if review is None:
        review = cycle_review(emp, cyc.id) or {}
    status = review.get("status")
    if status == "approved":
        return "approved"
    if sub is None:
        sub = store.submissions.find_one({"employee_id": emp, "date": iso})
    allowed = bool(sub and sub.get("reopened"))
    if sub and not allowed and status not in ("sent_back", "reopened"):
        return "submitted"
    if rules.deadline_passed(cyc, _now_ist()) and not allowed and status not in ("sent_back", "reopened"):
        return "deadline"
    return None


_READ_ONLY_TEXT = {
    "classic": "This day was filled in the classic timesheet - it is view only here",
    "approved": "This cycle has been approved and locked by your manager",
    "deadline": "The deadline for this cycle has passed",
    "submitted": "This day is submitted. Ask your admin if it needs to be changed",
    "no_cycle": "No payroll cycle has been set up for this date yet. Please ask your admin",
}


def _assert_editable(emp: str, d: date) -> None:
    reason = _read_only_reason(emp, d)
    if reason:
        raise HTTPException(409, _READ_ONLY_TEXT[reason])


def _day_location(entries: List[dict], sub: Optional[dict], draft: Optional[dict]) -> Optional[str]:
    if sub and sub.get("location"):
        return sub["location"]
    if draft and draft.get("location"):
        return draft["location"]
    return entries[0].get("location") if entries else None


def _day_payload(emp: str, d: date, cfg: dict) -> dict:
    iso = d.isoformat()
    tasks, nq_down = _my_tasks(emp, d)
    used = _hours_used(emp, [t.id for t in tasks])
    entries = list(store.entries.find({"employee_id": emp, "date": iso}).sort("created_at", 1))
    sub = store.submissions.find_one({"employee_id": emp, "date": iso})
    draft = store.drafts.find_one({"employee_id": emp, "date": iso})
    mgr = store.employees.find_one({"EmpID": emp}, {"ReportingEmpCode": 1, "ReportingEmpName": 1}) or {}
    cyc = payrolls.effective_cycle(d)
    review = cycle_review(emp, cyc.id) or {}
    reason = _read_only_reason(emp, d, review, entries, sub, cyc)
    total = round(sum(e["hours"] for e in entries if e.get("hours") is not None), 2)
    return {
        "date": iso, "weekday": d.strftime("%A"),
        "cycle": _cycle_view(cyc, emp, review),
        "location": _day_location(entries, sub, draft),
        "tasks": [_task_view(t, used, cfg) for t in tasks],
        "allocation_assumed_100": True,
        "entries": [_entry_view(e) for e in entries],
        "totals": {"task_hours": total, "rows": len(entries), "over_24": total > rules.MAX_DAY_HOURS},
        "submitted": bool(sub), "submitted_at": sub.get("submitted_at") if sub else None,
        "day_reopened": bool(sub and sub.get("reopened")),
        "read_only": reason is not None, "read_only_reason": reason,
        "read_only_text": _READ_ONLY_TEXT.get(reason) if reason else None,
        "reporting_manager": {"code": (mgr.get("ReportingEmpCode") or "").strip().upper(),
                              "name": mgr.get("ReportingEmpName") or ""},
        "nq_unavailable": nq_down,
        "nq_data_may_be_stale": nq_down or nq_cache.data_may_be_stale(),
    }


def _build_entry_docs(emp: str, d: date, body: DayIn) -> List[dict]:
    """Validate a DRAFT save and turn it into entry documents. Client / project / code come from NQ,
    the reporting manager from the employee record; nothing for those is taken from the browser."""
    location = (body.location or "").strip()
    if location not in rules.LOCATIONS:
        raise HTTPException(422, "Choose a location: " + ", ".join(rules.LOCATIONS))
    if location in rules.DAY_OFF_LOCATIONS:
        if body.entries:
            raise HTTPException(422, "A day off carries no work rows - remove them or change the location")
        return []
    if len(body.entries) > MAX_ENTRIES_PER_DAY:
        raise HTTPException(422, f"At most {MAX_ENTRIES_PER_DAY} rows per day")

    tasks, nq_down = _my_tasks(emp, d)
    if nq_down and any(not e.is_unplanned for e in body.entries):
        raise HTTPException(503, "Project data is unavailable right now - please try again shortly")
    by_id = {t.id: t for t in tasks}
    mgr = store.employees.find_one({"EmpID": emp}, {"ReportingEmpCode": 1, "ReportingEmpName": 1}) or {}
    cyc = rules.cycle_for(d)
    now = datetime.utcnow()
    seen, docs = set(), []
    for i, e in enumerate(body.entries, start=1):
        row = f"Row {i}"
        if e.hours is not None and not (0 <= e.hours <= rules.MAX_DAY_HOURS and round(e.hours, 2) == e.hours):
            raise HTTPException(422, f"{row}: hours must be between 0 and {rules.MAX_DAY_HOURS:g} with up to 2 decimals")
        remarks = (e.remarks or "").strip()
        doc = {
            "employee_id": emp, "date": d.isoformat(), "location": location,
            "remarks": remarks, "extra_remarks": (e.extra_remarks or "").strip(), "activity": remarks,           # `activity` mirrors remarks for older readers (digest)
            "hours": None if e.hours is None else round(float(e.hours), 2),
            "task_status": e.task_status, "cycle_id": cyc.id,
            "reporting_manager": (mgr.get("ReportingEmpCode") or "").strip().upper(),
            "reporting_manager_name": mgr.get("ReportingEmpName") or "",
            "approved": False, "locked": False, "created_at": now, "updated_at": now,
        }
        if e.is_unplanned:
            if e.task_id is not None:
                raise HTTPException(422, f"{row}: an unplanned row cannot have a task")
            doc.update({"task_id": None, "task_name": "", "client": "", "project": "", "project_code": "",
                        "is_unplanned": True, "unplanned_reason": remarks})
        else:
            t = by_id.get(e.task_id)
            if t is None:
                raise HTTPException(422, f"{row}: that task is not assigned to you for {d.isoformat()}")
            if t.id in seen:
                raise HTTPException(422, f"{row}: task listed twice - combine into one row")
            seen.add(t.id)
            doc.update({"task_id": t.id, "task_name": t.name, "client": t.client_name, "project": t.project_name,
                        "project_code": t.project_code, "is_unplanned": False, "unplanned_reason": ""})
        docs.append(doc)
    return docs


# ─────────────────────────────── routes ──────────────────────────────────────

@router.get("/enabled/{employee_id}")
def daily_enabled(employee_id: str, current_user: str = Depends(get_current_user)):
    emp = _require_self(employee_id, current_user)
    cfg = get_config()
    enabled = _is_enabled(emp, cfg)
    reason = None
    if not enabled:
        reason = "not_in_pilot" if cfg["pilot_only"] and emp not in cfg["pilot_employees"] else "free_text_employee"
    return {"enabled": enabled, "reason": reason}


@router.get("/cycle-days/{employee_id}")
def cycle_days(employee_id: str, date: Optional[str] = Query(None), current_user: str = Depends(get_current_user)):
    """The day strip: every day of the 10-day sub-cycle that contains `date` (default today) and its state."""
    emp = _require_self(employee_id, current_user)
    cfg = get_config()
    _require_enabled(emp, cfg)
    d = _parse_date(date, allow_future=True) if date else _today()
    return _strip_payload(emp, d, cfg)


def _strip_payload(emp: str, d: date, cfg: dict) -> dict:
    cyc = payrolls.effective_cycle(d)
    start, end = cyc.start.isoformat(), cyc.end.isoformat()
    per_day = {}
    for e in store.entries.find({"employee_id": emp, "date": {"$gte": start, "$lte": end}},
                                {"date": 1, "hours": 1, "location": 1, "legacy": 1}):
        row = per_day.setdefault(e["date"], {"hours": 0.0, "rows": 0, "location": None, "legacy": False})
        row["hours"] += e.get("hours") or 0.0
        row["rows"] += 1
        row["location"] = row["location"] or e.get("location")
        row["legacy"] = row["legacy"] or bool(e.get("legacy"))
    subs = {s["date"]: s for s in store.submissions.find({"employee_id": emp, "date": {"$gte": start, "$lte": end}})}
    drafts = {s["date"]: s for s in store.drafts.find({"employee_id": emp, "date": {"$gte": start, "$lte": end}})}
    today, days = _today(), []
    counts = {"submitted": 0, "saved": 0, "missing": 0}
    cur = cyc.start
    while cur <= cyc.end:
        iso = cur.isoformat()
        info = per_day.get(iso, {})
        working = cur.weekday() not in cfg["week_off"] and cur not in cfg["holidays"]
        if iso in subs:
            state = "submitted"
        elif iso in per_day or iso in drafts:
            state = "saved"
        elif cur > today:
            state = "future"
        elif working:
            state = "open" if cur == today else "missing"
        else:
            state = "off"
        if state in counts:
            counts[state] += 1
        days.append({"date": iso, "day": cur.day, "weekday": cur.strftime("%a"), "state": state, "working_day": working,
                     "location": (subs.get(iso) or drafts.get(iso) or {}).get("location") or info.get("location"),
                     "hours": round(info.get("hours", 0.0), 2), "classic": bool(info.get("legacy"))})
        cur += timedelta(days=1)
    counts["missing"] += sum(1 for x in days if x["state"] == "open")        # today still counts as "to do"
    return {"cycle": _cycle_view(cyc, emp), "today": today.isoformat(), "selected": d.isoformat(), "days": days,
            "summary": counts, "prev_date": (cyc.start - timedelta(days=1)).isoformat(),
            "next_date": (cyc.end + timedelta(days=1)).isoformat() if cyc.end < today else None}


@router.get("/page/{employee_id}")
def page(employee_id: str, date: Optional[str] = Query(None), current_user: str = Depends(get_current_user)):
    """Everything the My day screen needs in ONE request: whether the person uses it, the day and the day strip.
    (One round trip instead of enabled + cycle-days + day + cycle-days, which matters over a slow link.)"""
    emp = _require_self(employee_id, current_user)
    cfg = get_config()
    if not _is_enabled(emp, cfg):
        return {"enabled": False, "reason": "not_in_pilot" if cfg["pilot_only"] and emp not in cfg["pilot_employees"] else "free_text_employee"}
    indexes.ensure_once()
    d = _parse_date(date, allow_future=True) if date else _today()
    return {"enabled": True, "day": _day_payload(emp, d, cfg), "strip": _strip_payload(emp, d, cfg)}


@router.get("/day/{employee_id}")
def get_day(employee_id: str, date: str, current_user: str = Depends(get_current_user)):
    emp = _require_self(employee_id, current_user)
    cfg = get_config()
    _require_enabled(emp, cfg)
    indexes.ensure_once()
    return _day_payload(emp, _parse_date(date), cfg)


@router.put("/day/{employee_id}/{date}")
def save_day(employee_id: str, date: str, body: DayIn, current_user: str = Depends(get_current_user)):
    """Save the day as a DRAFT (autosave). Editing a submitted day withdraws its submission."""
    emp = _require_self(employee_id, current_user)
    cfg = get_config()
    _require_enabled(emp, cfg)
    d = _parse_date(date)
    _assert_editable(emp, d)
    docs = _build_entry_docs(emp, d, body)
    iso = d.isoformat()
    old_docs = list(store.entries.find({"employee_id": emp, "date": iso}, {"created_at": 1}))
    created = min((o["created_at"] for o in old_docs if o.get("created_at")), default=None)
    if created:
        for doc in docs:
            doc["created_at"] = created
    # insert the new rows BEFORE removing the old ones: a failed insert can never leave the day empty
    if docs:
        store.entries.insert_many(docs)
    store.entries.delete_many({"_id": {"$in": [o["_id"] for o in old_docs]}})
    store.submissions.delete_one({"employee_id": emp, "date": iso})
    store.drafts.update_one({"employee_id": emp, "date": iso},
                            {"$set": {"employee_id": emp, "date": iso, "location": body.location.strip(),
                                      "cycle_id": rules.cycle_for(d).id, "saved_at": datetime.utcnow()}}, upsert=True)
    hrms_reco.safe_recompute_day(emp, iso)
    return _day_payload(emp, d, cfg)


@router.post("/day/{employee_id}/{date}/submit")
def submit_day(employee_id: str, date: str, current_user: str = Depends(get_current_user)):
    """Strict check of the SAVED day, then mark it submitted."""
    emp = _require_self(employee_id, current_user)
    cfg = get_config()
    _require_enabled(emp, cfg)
    d = _parse_date(date)
    _assert_editable(emp, d)
    iso = d.isoformat()
    entries = list(store.entries.find({"employee_id": emp, "date": iso}).sort("created_at", 1))
    sub = store.submissions.find_one({"employee_id": emp, "date": iso})
    draft = store.drafts.find_one({"employee_id": emp, "date": iso})
    location = _day_location(entries, sub, draft)
    if not location:
        raise HTTPException(422, "Choose a location for the day first")
    problems = rules.day_submit_errors(location, entries)
    if problems:
        raise HTTPException(422, "; ".join(problems[:5]))
    store.submissions.update_one(
        {"employee_id": emp, "date": iso},
        {"$set": {"employee_id": emp, "date": iso, "submitted_at": datetime.utcnow(), "location": location,
                  "cycle_id": rules.cycle_for(d).id}, "$unset": {"reopened": ""}}, upsert=True)
    store.drafts.delete_one({"employee_id": emp, "date": iso})
    hrms_reco.safe_recompute_day(emp, iso)
    return _day_payload(emp, d, cfg)
