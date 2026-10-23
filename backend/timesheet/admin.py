# backend/timesheet/admin.py
"""
Admin setup for the timesheet (admins only, checked on EVERY endpoint):

  GET    /timesheet/v2/admin/overview                          payrolls, working rules, who uses My day
  POST   /timesheet/v2/admin/payrolls                          create a payroll (its three sub-cycles appear automatically)
  PUT    /timesheet/v2/admin/payrolls/{payroll}/cycles/{cycle} change a sub-cycle's deadline
  DELETE /timesheet/v2/admin/payrolls/{payroll}                delete a payroll that has no data yet
  PUT    /timesheet/v2/admin/settings                          hours per day, week-off days, default deadline days, holidays
  PUT    /timesheet/v2/admin/access                            who uses My day (all / a list) and named extra employees
  GET    /timesheet/v2/admin/submitted-days                    an employee's submitted days
  POST   /timesheet/v2/admin/reopen-day                        allow ONE employee to change ONE submitted day

Every change is recorded in cycle_reviews (kind "admin_change" / "day_reopen") with who and when.
"""
import re
from datetime import date, datetime, timedelta
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from backend.auth import get_current_user
from backend.cycle.locks import cycle_review
from backend.cycle.store import store
from backend.metrics import access
from backend.timesheet import payrolls, rules, scope

router = APIRouter(prefix="/timesheet/v2/admin", tags=["Timesheet admin"])
CONFIG_ID = "timesheet"
_CODE = re.compile(r"^[A-Za-z0-9_-]{2,20}$")
MAX_HOLIDAYS = 400
MAX_CODES = 500


def _admin(current_user: str) -> str:
    me = access.me(current_user)
    if not access.is_admin(me):
        raise HTTPException(403, "Only admins can change the timesheet setup")
    return me


def _log(me: str, what: str, detail: dict) -> None:
    store.reviews.insert_one({"kind": "admin_change", "by": me, "at": datetime.utcnow(), "what": what, "detail": detail})


def _iso(value: str, what: str) -> str:
    try:
        return date.fromisoformat(str(value)[:10]).isoformat()
    except ValueError:
        raise HTTPException(422, f"{what} must be a date (YYYY-MM-DD)")


def _codes(raw: List[str]) -> List[str]:
    out = sorted({str(c).strip().upper() for c in raw if str(c).strip()})
    if len(out) > MAX_CODES or any(not _CODE.match(c) for c in out):
        raise HTTPException(422, "Employee codes may contain letters, digits, - and _ only")
    return out


# ─────────────────────────────── overview ────────────────────────────────────

def _settings_out(s: dict, doc: dict) -> dict:
    return {"standard_hours": s["standard_hours"], "week_off_days": list(s["week_off"]), "deadline_days": s["deadline_days"],
            "holidays": [{"date": d.isoformat(), "name": n} for d, n in sorted(s["holidays"].items())]}


@router.get("/overview")
def overview(current_user: str = Depends(get_current_user)):
    _admin(current_user)
    doc = store.config.find_one({"_id": CONFIG_ID}) or {}
    counts = {r["_id"]: r["n"] for r in store.entries.aggregate([{"$group": {"_id": "$cycle_id", "n": {"$sum": 1}}}])}
    out = []
    for p in payrolls.list_payrolls():
        out.append({**{k: p[k] for k in ("_id", "label", "start", "end", "created_by")},
                    "cycles": [{**c, "entries": counts.get(c["id"], 0)} for c in p["cycles"]]})
    return {"payrolls": out, "settings": _settings_out(payrolls.settings_from(doc), doc),
            "access": {"scope": "pilot" if scope.pilot_only(doc) else "all",
                       "pilot_employees": sorted(scope.pilot_codes(doc)), "include": sorted(scope.include_codes(doc))},
            "today": datetime.utcnow().date().isoformat()}


# ─────────────────────────────── payrolls ────────────────────────────────────

class PayrollIn(BaseModel):
    month: str = Field(..., pattern=r"^\d{4}-(0[1-9]|1[0-2])$")          # the month the payroll ENDS in
    deadline_days: Optional[int] = Field(None, ge=0, le=60)


@router.post("/payrolls")
def create_payroll(body: PayrollIn, current_user: str = Depends(get_current_user)):
    me = _admin(current_user)
    if not 2000 <= int(body.month[:4]) <= 2100:
        raise HTTPException(422, "Choose a sensible year")
    if store.payrolls.find_one({"_id": body.month}, {"_id": 1}):
        raise HTTPException(409, f"The payroll {rules.payroll_label(body.month)} already exists")
    dd = body.deadline_days if body.deadline_days is not None else payrolls.settings()["deadline_days"]
    doc = payrolls.build_payroll(body.month, dd, me)
    store.payrolls.insert_one(doc)
    payrolls.invalidate()
    _log(me, "payroll created", {"payroll": body.month, "deadline_days": dd})
    return {"created": body.month, "label": doc["label"], "cycles": doc["cycles"]}


class DeadlineIn(BaseModel):
    deadline: str


@router.put("/payrolls/{payroll_id}/cycles/{cycle_id}")
def set_deadline(payroll_id: str, cycle_id: str, body: DeadlineIn, current_user: str = Depends(get_current_user)):
    me = _admin(current_user)
    doc = store.payrolls.find_one({"_id": payroll_id})
    cyc = next((c for c in (doc or {}).get("cycles", []) if c["id"] == cycle_id), None)
    if not cyc:
        raise HTTPException(404, "That payroll or cycle does not exist")
    deadline = _iso(body.deadline, "Deadline")
    if deadline < cyc["end"]:
        raise HTTPException(422, f"The deadline cannot be before the cycle ends ({cyc['end']})")
    store.payrolls.update_one({"_id": payroll_id}, {"$set": {"cycles.$[c].deadline": deadline}}, array_filters=[{"c.id": cycle_id}])
    payrolls.invalidate()
    _log(me, "deadline changed", {"cycle": cycle_id, "from": cyc["deadline"], "to": deadline})
    return {"cycle": cycle_id, "deadline": deadline}


@router.delete("/payrolls/{payroll_id}")
def delete_payroll(payroll_id: str, current_user: str = Depends(get_current_user)):
    me = _admin(current_user)
    doc = store.payrolls.find_one({"_id": payroll_id})
    if not doc:
        raise HTTPException(404, "That payroll does not exist")
    ids = [c["id"] for c in doc["cycles"]]
    used = (store.entries.count_documents({"cycle_id": {"$in": ids}}, limit=1)
            or store.submissions.count_documents({"cycle_id": {"$in": ids}}, limit=1)
            or store.drafts.count_documents({"cycle_id": {"$in": ids}}, limit=1)
            or store.reviews.count_documents({"kind": "approval", "cycle_id": {"$in": ids}}, limit=1))
    if used:
        raise HTTPException(409, "This payroll already has timesheet data, so it cannot be deleted")
    store.payrolls.delete_one({"_id": payroll_id})
    payrolls.invalidate()
    _log(me, "payroll deleted", {"payroll": payroll_id})
    return {"deleted": payroll_id}


# ─────────────────────────────── working rules ───────────────────────────────

class HolidayIn(BaseModel):
    date: str
    name: str = Field("", max_length=80)


class SettingsIn(BaseModel):
    standard_hours: float = Field(..., gt=0, le=24)
    week_off_days: List[int]
    deadline_days: int = Field(..., ge=0, le=60)
    holidays: List[HolidayIn] = []


@router.put("/settings")
def save_settings(body: SettingsIn, current_user: str = Depends(get_current_user)):
    me = _admin(current_user)
    off = sorted(set(body.week_off_days))
    if any(not 0 <= d <= 6 for d in off) or len(off) >= 7:
        raise HTTPException(422, "Week-off days must be between Monday and Sunday, and not every day")
    if len(body.holidays) > MAX_HOLIDAYS:
        raise HTTPException(422, f"At most {MAX_HOLIDAYS} holidays")
    names, days = {}, set()
    for h in body.holidays:
        iso = _iso(h.date, "Holiday date")
        days.add(iso)
        names[iso] = h.name.strip()
    store.config.update_one({"_id": CONFIG_ID}, {"$set": {
        "standard_hours": round(body.standard_hours, 2), "week_off_days": off, "deadline_days": body.deadline_days,
        "holidays": sorted(days), "holiday_names": names}}, upsert=True)
    _log(me, "working rules changed", {"standard_hours": body.standard_hours, "week_off_days": off,
                                       "deadline_days": body.deadline_days, "holidays": len(days)})
    return {"saved": True}


# ─────────────────────────────── who uses My day ─────────────────────────────

class AccessIn(BaseModel):
    scope: Literal["all", "pilot"]
    pilot_employees: List[str] = []
    include: List[str] = []


@router.put("/access")
def save_access(body: AccessIn, current_user: str = Depends(get_current_user)):
    me = _admin(current_user)
    pilot, include = _codes(body.pilot_employees), _codes(body.include)
    store.config.update_one({"_id": CONFIG_ID}, {"$set": {
        "timesheet_scope": body.scope, "pilot_employees": pilot, "new_timesheet_include": include}}, upsert=True)
    _log(me, "access changed", {"scope": body.scope, "pilot": len(pilot), "include": len(include)})
    return {"saved": True}


# ─────────────────────────────── allow changes to a submitted day ────────────

@router.get("/submitted-days")
def submitted_days(employee: str = Query(...), date_from: str = Query(..., alias="from"), date_to: str = Query(..., alias="to"),
                   current_user: str = Depends(get_current_user)):
    _admin(current_user)
    emp = employee.strip().upper()
    if not _CODE.match(emp):
        raise HTTPException(422, "Enter an employee code")
    a, b = _iso(date_from, "From"), _iso(date_to, "To")
    if b < a or (date.fromisoformat(b) - date.fromisoformat(a)).days > 62:
        raise HTTPException(422, "Choose a range of at most 62 days")
    hours = {r["_id"]: round(r["h"], 2) for r in store.entries.aggregate([
        {"$match": {"employee_id": emp, "date": {"$gte": a, "$lte": b}, "hours": {"$ne": None}}},
        {"$group": {"_id": "$date", "h": {"$sum": "$hours"}}}])}
    out = []
    for s in store.submissions.find({"employee_id": emp, "date": {"$gte": a, "$lte": b}}).sort("date", 1):
        review = cycle_review(emp, s.get("cycle_id") or "") or {}
        out.append({"date": s["date"], "location": s.get("location"), "hours": hours.get(s["date"], 0.0),
                    "submitted_at": s.get("submitted_at"), "cycle_id": s.get("cycle_id"), "classic": bool(s.get("legacy")),
                    "cycle_status": review.get("status", "pending"), "reopened": s.get("reopened")})
    name = (store.employees.find_one({"EmpID": emp}, {"Emp Name": 1}) or {}).get("Emp Name", "")
    return {"employee_id": emp, "employee_name": name, "days": out}


class ReopenIn(BaseModel):
    employee_id: str
    date: str
    reason: str = Field(..., min_length=3, max_length=500)


@router.post("/reopen-day")
def reopen_day(body: ReopenIn, current_user: str = Depends(get_current_user)):
    me = _admin(current_user)
    emp, day = body.employee_id.strip().upper(), _iso(body.date, "Date")
    sub = store.submissions.find_one({"employee_id": emp, "date": day})
    if not sub:
        raise HTTPException(404, "That day is not submitted")
    if sub.get("legacy"):
        raise HTTPException(409, "That day was filled in the classic timesheet and cannot be changed here")
    if sub.get("reopened"):
        raise HTTPException(409, "That day is already open for changes")
    if (cycle_review(emp, sub.get("cycle_id") or "") or {}).get("status") == "approved":
        raise HTTPException(409, "The manager has approved this cycle. Unlock the cycle first, then allow the day")
    now = datetime.utcnow()
    store.submissions.update_one({"_id": sub["_id"]}, {"$set": {"reopened": {"by": me, "at": now, "reason": body.reason.strip()}}})
    store.reviews.insert_one({"kind": "day_reopen", "employee_id": emp, "date": day, "cycle_id": sub.get("cycle_id"),
                              "by": me, "at": now, "reason": body.reason.strip()})
    return {"employee_id": emp, "date": day, "reopened": True}
