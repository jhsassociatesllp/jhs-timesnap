# backend/hrms/router.py
"""
HRMS attendance upload (admin only). The comparison of typed hours with HRMS hours is shown per employee in
Review team (backend/cycle/router.py), computed on demand from what is stored here.

Roles (checked on EVERY endpoint): admin = has_admin_module(user, "timesheet"): upload and history.
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


def _last_upload(admin: bool = True) -> Optional[dict]:
    """Managers only learn WHEN data was last uploaded and which dates it covers."""
    u = store.uploads.find_one({"status": {"$ne": "failed"}}, sort=[("uploaded_at", -1)])
    if not u:
        return None
    out = {"uploaded_at": u.get("uploaded_at"), "date_from": u.get("date_from"), "date_to": u.get("date_to")}
    if admin:
        out.update(file_name=u.get("file_name"), uploaded_by=u.get("uploaded_by"))
    return out


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
    """Import the file (upsert by employee_id + date, so re-importing is harmless), record it and derive holidays.
    Typed hours are never changed; the comparison with HRMS is shown per employee in Review team."""
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
        "errors": res.errors[:100], "warnings": res.warnings, "status": "importing",
    }).inserted_id

    ops = [UpdateOne(
        {"employee_id": r["employee_id"], "date": r["date"]},
        {"$set": {**r, "upload_id": str(upload_id), "updated_at": now}, "$setOnInsert": {"created_at": now}},
        upsert=True) for r in res.rows]
    try:
        bulk = store.hrms.bulk_write(ops, ordered=False)
        holidays = _holiday_dates(res.rows)
        if holidays:
            store.config.update_one({"_id": reco.CONFIG_ID}, {"$addToSet": {"holidays": {"$each": holidays}}},
                                    upsert=True)
        outcome = {}              # hours are compared with HRMS on demand in Review team; nothing is precomputed per row
    except Exception:
        # the log must never claim an import that did not finish (re-running the same file is safe)
        store.uploads.update_one({"_id": upload_id}, {"$set": {"status": "failed"}})
        raise
    store.uploads.update_one({"_id": upload_id}, {"$set": {
        "status": "done", "holidays_added": holidays, "reco_counts": outcome}})
    return {"upload_id": str(upload_id), "rows_imported": len(res.rows), "rows_new": bulk.upserted_count,
            "rows_existing": len(res.rows) - bulk.upserted_count, "errors": len(res.errors),
            "warnings": res.warnings, "date_from": res.date_from, "date_to": res.date_to,
            "holidays_added": holidays, "reco_counts": outcome}


@router.get("/uploads")
def list_uploads(current_user: str = Depends(get_current_user)):
    _require_admin(current_user)
    uploads = list(store.uploads.find({}, {"errors": 0}).sort("uploaded_at", -1).limit(20))
    for u in uploads:
        u["_id"] = str(u["_id"])
    today = _today()
    return {"uploads": uploads, "last_upload": _last_upload(),
            "awaiting_dates": _awaiting_dates(today - timedelta(days=30), today)}
