# backend/hrms/router.py
"""
HRMS upload (admin only) and the reconciliation views.

Roles (checked on EVERY endpoint):
  admin    = has_admin_module(user, "timesheet"): upload, history, firm-wide reco, review any row
  manager  = has reportees (Employee_details.ReportingEmpCode == user): reco for own reportees only,
             accept / send back only for own reportees
  employee = nothing here (own reco status is shown on the daily timesheet)
"""
import hashlib
import os
from datetime import date, datetime, timedelta
from typing import List, Optional

import pytz
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from pymongo import UpdateOne

from backend.access_manager.router import has_admin_module
from backend.auth import get_current_user
from backend.hrms import reco
from backend.hrms.parser import MAX_BYTES, HrmsFileError, parse_hrms
from backend.hrms.rules import FLAGGED_RESULTS
from backend.hrms.reco import store

router = APIRouter(prefix="/hrms", tags=["HRMS"])
IST = pytz.timezone("Asia/Kolkata")
MAX_RANGE_DAYS = 62
HOLIDAY_MIN_ROWS = 3        # a date needs this many rows in the file ...
HOLIDAY_SHARE = 0.9         # ... and this share of them marked as a holiday


# ─────────────────────────────── roles ───────────────────────────────────────

def _me(current_user: str) -> str:
    return (current_user or "").strip().upper()


def _is_admin(user: str) -> bool:
    return has_admin_module(user, "timesheet")


def _reportee_ids(manager: str) -> List[str]:
    return [d["EmpID"].strip().upper() for d in
            store.employees.find({"ReportingEmpCode": manager}, {"EmpID": 1}) if d.get("EmpID")]


def _require_admin(current_user: str) -> str:
    me = _me(current_user)
    if not _is_admin(me):
        raise HTTPException(403, "Admin access required")
    return me


def _can_review(me: str, employee_id: str) -> bool:
    if _is_admin(me):
        return True
    emp = store.employees.find_one({"EmpID": employee_id.strip().upper()}, {"ReportingEmpCode": 1}) or {}
    return (emp.get("ReportingEmpCode") or "").strip().upper() == me


# ─────────────────────────────── helpers ─────────────────────────────────────

def _today() -> date:
    return datetime.now(IST).date()


def _read_upload(file: UploadFile) -> bytes:
    content = file.file.read(MAX_BYTES + 1)
    if len(content) > MAX_BYTES:
        raise HTTPException(413, "File is larger than 10 MB")
    return content


def _parse(file: UploadFile):
    content = _read_upload(file)
    try:
        res = parse_hrms(content, os.path.basename(file.filename or ""), reco.config()["status_codes"])
    except HrmsFileError as e:
        raise HTTPException(400, str(e))
    return content, res


def _preview_dict(content: bytes, res, file_name: str) -> dict:
    ids = {r["employee_id"] for r in res.rows}
    known = {d["EmpID"].strip().upper() for d in
             store.employees.find({"EmpID": {"$in": list(ids)}}, {"EmpID": 1}) if d.get("EmpID")}
    sha = hashlib.sha256(content).hexdigest()
    prior = store.uploads.find_one({"sha256": sha}, {"uploaded_at": 1, "uploaded_by": 1})
    warnings = list(res.warnings)
    if ids - known:
        warnings.append(f"{len(ids - known)} employee code(s) are not in Employee_details "
                        "(imported, but they cannot be matched to a person)")
    if prior:
        warnings.append("This exact file was imported before; re-importing changes nothing")
    return {
        "file_name": file_name, "sha256": sha, "total_rows": res.total_rows, "valid_rows": len(res.rows),
        "error_count": len(res.errors), "errors": res.errors[:50], "warnings": warnings,
        "date_from": res.date_from, "date_to": res.date_to, "employees": len(ids),
        "unknown_employees": len(ids - known), "already_imported": bool(prior),
        "sample": res.rows[:5],
    }


def _holiday_dates(rows: List[dict]) -> List[str]:
    per_date = {}
    for r in rows:
        t = per_date.setdefault(r["date"], [0, 0])
        t[0] += 1
        t[1] += 1 if r["kind"] == "holiday" else 0
    return sorted(d for d, (n, h) in per_date.items() if n >= HOLIDAY_MIN_ROWS and h / n >= HOLIDAY_SHARE)


def _awaiting_dates(date_from: date, date_to: date) -> List[str]:
    """Past working days in the range with no HRMS rows at all."""
    doc = store.config.find_one({"_id": reco.CONFIG_ID}) or {}
    holidays = {str(h)[:10] for h in doc.get("holidays", []) or []}
    have = {d for d in store.hrms.distinct("date", {"date": {"$gte": date_from.isoformat(),
                                                             "$lte": date_to.isoformat()}})}
    out, d, today = [], date_from, _today()
    while d <= min(date_to, today):
        iso = d.isoformat()
        if d.weekday() < 5 and iso not in holidays and iso not in have:
            out.append(iso)
        d += timedelta(days=1)
    return out


def _last_upload() -> Optional[dict]:
    u = store.uploads.find_one({}, sort=[("uploaded_at", -1)])
    if not u:
        return None
    return {"file_name": u.get("file_name"), "uploaded_at": u.get("uploaded_at"),
            "date_from": u.get("date_from"), "date_to": u.get("date_to"),
            "uploaded_by": u.get("uploaded_by")}


def _parse_range(date_from: str, date_to: str):
    try:
        a, b = date.fromisoformat(date_from), date.fromisoformat(date_to)
    except ValueError:
        raise HTTPException(400, "from/to must be YYYY-MM-DD")
    if b < a:
        raise HTTPException(400, "'to' is before 'from'")
    if (b - a).days > MAX_RANGE_DAYS:
        raise HTTPException(400, f"Range is limited to {MAX_RANGE_DAYS} days")
    return a, b


# ─────────────────────────────── routes ──────────────────────────────────────

@router.get("/access")
def my_access(current_user: str = Depends(get_current_user)):
    me = _me(current_user)
    return {"is_admin": _is_admin(me),
            "is_manager": store.employees.find_one({"ReportingEmpCode": me}, {"_id": 1}) is not None}


@router.post("/upload/preview")
def upload_preview(file: UploadFile = File(...), current_user: str = Depends(get_current_user)):
    """Parse the file and report what an import would do. Writes nothing."""
    _require_admin(current_user)
    content, res = _parse(file)
    return _preview_dict(content, res, os.path.basename(file.filename or "")[:200])


@router.post("/upload/commit")
def upload_commit(file: UploadFile = File(...), current_user: str = Depends(get_current_user)):
    """Import the file (upsert by employee_id + date, so re-importing is harmless),
    record it, derive holidays, autofill one-task days and reconcile."""
    me = _require_admin(current_user)
    content, res = _parse(file)
    if not res.rows:
        raise HTTPException(400, "No valid rows to import")
    name = os.path.basename(file.filename or "")[:200]
    now = datetime.utcnow()
    reco.ensure_indexes()

    upload_id = store.uploads.insert_one({
        "file_name": name, "sha256": hashlib.sha256(content).hexdigest(), "uploaded_by": me,
        "uploaded_at": now, "date_from": res.date_from, "date_to": res.date_to,
        "rows_total": res.total_rows, "rows_imported": len(res.rows), "rows_errors": len(res.errors),
        "errors": res.errors[:100], "warnings": res.warnings,
    }).inserted_id

    ops = [UpdateOne(
        {"employee_id": r["employee_id"], "date": r["date"]},
        {"$set": {**r, "upload_id": str(upload_id), "updated_at": now}, "$setOnInsert": {"created_at": now}},
        upsert=True) for r in res.rows]
    bulk = store.hrms.bulk_write(ops, ordered=False)

    holidays = _holiday_dates(res.rows)
    if holidays:
        store.config.update_one({"_id": reco.CONFIG_ID}, {"$addToSet": {"holidays": {"$each": holidays}}},
                                upsert=True)
    outcome = reco.recompute_range(res.date_from, res.date_to)
    autofilled = outcome.pop("_autofilled", 0)
    store.uploads.update_one({"_id": upload_id}, {"$set": {
        "holidays_added": holidays, "autofilled_entries": autofilled, "reco_counts": outcome}})
    return {"upload_id": str(upload_id), "rows_imported": len(res.rows), "rows_new": bulk.upserted_count,
            "rows_existing": len(res.rows) - bulk.upserted_count, "errors": len(res.errors),
            "warnings": res.warnings, "date_from": res.date_from, "date_to": res.date_to,
            "holidays_added": holidays, "autofilled_entries": autofilled, "reco_counts": outcome}


@router.get("/uploads")
def list_uploads(current_user: str = Depends(get_current_user)):
    _require_admin(current_user)
    uploads = list(store.uploads.find({}, {"errors": 0}).sort("uploaded_at", -1).limit(20))
    for u in uploads:
        u["_id"] = str(u["_id"])
    today = _today()
    return {"uploads": uploads, "last_upload": _last_upload(),
            "awaiting_dates": _awaiting_dates(today - timedelta(days=30), today)}


@router.get("/reco")
def reco_view(date_from: str = Query(..., alias="from"), date_to: str = Query(..., alias="to"),
              manager: Optional[str] = None, current_user: str = Depends(get_current_user)):
    me = _me(current_user)
    a, b = _parse_range(date_from, date_to)
    admin = _is_admin(me)
    query = {"date": {"$gte": a.isoformat(), "$lte": b.isoformat()}}
    if admin:
        if manager:
            query["employee_id"] = {"$in": _reportee_ids(manager.strip().upper())}
    else:
        team = _reportee_ids(me)
        if not team:
            raise HTTPException(403, "Only managers and admins can view reconciliation")
        query["employee_id"] = {"$in": team}
    rows = list(store.reco.find(query).sort([("date", -1), ("employee_id", 1)]).limit(5000))
    names = {d["EmpID"].strip().upper(): d.get("Emp Name", "") for d in
             store.employees.find({"EmpID": {"$in": list({r["employee_id"] for r in rows})}},
                                  {"EmpID": 1, "Emp Name": 1}) if d.get("EmpID")}
    summary = {k: 0 for k in ("matched", "short", "over", "no_punch", "not_filled", "leave")}
    out = []
    for r in rows:
        summary[r["result"]] = summary.get(r["result"], 0) + 1
        out.append({"employee_id": r["employee_id"], "employee_name": names.get(r["employee_id"], ""),
                    "date": r["date"], "hrms_net": r.get("hrms_net"), "timesheet_hours": r.get("timesheet_hours"),
                    "diff": r.get("diff"), "result": r["result"], "reason": r.get("reason", ""),
                    "status": r.get("status", "open"), "manager_note": r.get("manager_note", "")})
    return {"summary": summary, "rows": out, "last_upload": _last_upload(),
            "awaiting_dates": _awaiting_dates(a, b)}


class ReviewIn(BaseModel):
    note: str = Field("", max_length=500)


def _review(employee_id: str, day: str, status: str, note: str, current_user: str) -> dict:
    me = _me(current_user)
    emp = employee_id.strip().upper()
    if not _can_review(me, emp):
        raise HTTPException(403, "Unauthorized")
    try:
        iso = date.fromisoformat(day).isoformat()
    except ValueError:
        raise HTTPException(400, "date must be YYYY-MM-DD")
    row = store.reco.find_one({"employee_id": emp, "date": iso})
    if not row:
        raise HTTPException(404, "No reconciliation row for that day")
    if row["result"] not in FLAGGED_RESULTS:
        raise HTTPException(422, "Only flagged days (short, over, no punch, not filled) can be reviewed")
    note = (note or "").strip()
    if status == "sent_back" and not note:
        raise HTTPException(422, "Add a comment explaining what to fix")
    store.reco.update_one({"employee_id": emp, "date": iso}, {"$set": {
        "status": status, "manager_note": note, "reviewed_by": me, "reviewed_at": datetime.utcnow()}})
    return {"employee_id": emp, "date": iso, "status": status, "manager_note": note}


@router.post("/reco/{employee_id}/{day}/accept")
def accept(employee_id: str, day: str, body: ReviewIn, current_user: str = Depends(get_current_user)):
    return _review(employee_id, day, "accepted", body.note, current_user)


@router.post("/reco/{employee_id}/{day}/send-back")
def send_back(employee_id: str, day: str, body: ReviewIn, current_user: str = Depends(get_current_user)):
    return _review(employee_id, day, "sent_back", body.note, current_user)
