# backend/appraisal/router.py
"""
All /appraisal/* API routes — with full 3-tier approval system.

Role resolution logic:
  - _resolve_role() returns the user's NATURAL role (partner/tl/employee/admin)
    ignoring admin status — so a senior partner stays "partner" for
    Pending/Approved/Rejected tabs.
  - _is_admin() is checked SEPARATELY wherever admin-level access is needed
    (e.g. analysis always shows full company data if user is in admin list).

Role definitions:
  admin   → present in appraisal_admin_collection AND has no other natural role
  partner → Grade Name == "PnD" in employee_details (Timesheets DB)
  tl      → present as ReportingEmpCode in reporting_managers (Timesheets DB)
  employee→ everyone else

A user who is in admin list AND is a partner → resolves as "partner"
  but _is_admin() returns True → gets full company Analysis.

Status flow:
  submitted → TL_approved / TL_rejected → PnD_approved / PnD_rejected
"""

import io
import re
from datetime import date, datetime
from typing import Optional

import pandas as pd
from bson import ObjectId
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from backend.auth import get_current_user
from backend.database import (
    employee_details_collection,          # Timesheets DB
    appraisal_collection,                 # Appraisal DB  (Appraisal_data)
    appraisal_admin_collection,           # Appraisal DB  (admin_details)
    appraisal_cycles_collection,          # Appraisal DB  (Appraisal_cycles)
    appraisal_eligibility_collection,     # Appraisal DB  (Appraisal_eligibility)
    appraisal_upload_history_collection,  # Appraisal DB  (Appraisal_upload_history)
)
from backend.appraisal.models import (
    AppraisalSaveRequest, AppraisalReviewRequest, CycleToggleRequest,
    CreateCycleRequest, UpdateCycleRequest,
)
from backend.appraisal.questions import (
    get_questions_for_employee,
    calculate_score,
)

from backend.database import db as timesheets_db

reporting_managers_collection = timesheets_db["Reporting_managers"]

router = APIRouter(prefix="/appraisal", tags=["Appraisal"])

try:
    appraisal_eligibility_collection.create_index(
        [("quarter_id", 1), ("employee_code", 1)], unique=True, name="quarter_employee_unique"
    )
except Exception:
    pass

# ─────────────────────────────────────────────────────────────────────────────
# Role helpers
# ─────────────────────────────────────────────────────────────────────────────

def _is_admin(emp_id: str) -> bool:
    """Check if emp_id is in the admin list. Independent of natural role."""
    doc = appraisal_admin_collection.find_one({})
    if not doc:
        return False
    codes = doc.get("employee_codes", [])
    return emp_id.upper() in [c.upper() for c in codes]


def _is_partner(emp_id: str) -> bool:
    emp = employee_details_collection.find_one({"EmpID": emp_id.strip().upper()})
    if not emp:
        return False
    return (emp.get("Grade Name", "") or "").strip().upper() == "PND"


def _is_tl(emp_id: str) -> bool:
    doc = reporting_managers_collection.find_one(
        {"ReportingEmpCode": emp_id.strip().upper()}
    )
    return doc is not None


def _resolve_role(emp_id: str) -> str:
    """
    Return the user's NATURAL role: 'partner' | 'tl' | 'admin' | 'employee'

    KEY CHANGE: Admin status does NOT override natural role anymore.
    A senior partner who is in the admin list resolves as 'partner' here,
    so their Pending/Approved/Rejected tabs show only their own employees.
    Use _is_admin() separately to grant extra privileges (e.g. full Analysis).

    Pure admins (in admin list but not partner/TL) still get 'admin'.
    """
    uid = emp_id.strip().upper()
    # Natural role takes priority over admin flag
    if _is_partner(uid):
        return "partner"
    if _is_tl(uid):
        return "tl"
    # Only returns 'admin' if user has no other natural role
    if _is_admin(uid):
        return "admin"
    return "employee"


def _get_tl_for_employee(emp_id: str) -> Optional[str]:
    emp = employee_details_collection.find_one({"EmpID": emp_id.strip().upper()})
    if not emp:
        return None
    return emp.get("ReportingEmpCode", "")


def _get_partner_for_employee(emp_id: str) -> Optional[str]:
    emp = employee_details_collection.find_one({"EmpID": emp_id.strip().upper()})
    if not emp:
        return None
    return emp.get("PartnerEmpCode", "")


def _employees_under_tl(tl_id: str) -> list[dict]:
    return list(employee_details_collection.find(
        {"ReportingEmpCode": tl_id.strip().upper()},
        {"EmpID": 1, "Emp Name": 1, "Designation Name": 1}
    ))


def _employees_under_partner(partner_id: str) -> list[dict]:
    return list(employee_details_collection.find(
        {"PartnerEmpCode": partner_id.strip().upper()},
        {"EmpID": 1, "Emp Name": 1, "Designation Name": 1, "ReportingEmpCode": 1}
    ))


def _tls_under_partner(partner_id: str) -> list[str]:
    emps = _employees_under_partner(partner_id)
    tl_codes = set()
    for e in emps:
        rc = e.get("ReportingEmpCode", "")
        if rc:
            tl_codes.add(rc.upper())
    return list(tl_codes)


# ─────────────────────────────────────────────────────────────────────────────
# Quarter / cycle helpers
# ─────────────────────────────────────────────────────────────────────────────

def _slugify_quarter_id(label: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", label.strip()).strip("_").upper()
    return f"KRA_{slug}"


def _get_live_cycle() -> Optional[dict]:
    return appraisal_cycles_collection.find_one({"status": "live"})


def _get_cycle(quarter_id: str) -> Optional[dict]:
    return appraisal_cycles_collection.find_one({"quarter_id": quarter_id})


def _resolve_quarter_id(requested: Optional[str]) -> Optional[str]:
    """Explicit quarter_id if given, else the live quarter's id, else None."""
    if requested:
        return requested
    live = _get_live_cycle()
    return live["quarter_id"] if live else None


def _get_current_period() -> str:
    """Display label of the live quarter (kept for the 'period' field stored
    on Appraisal_data records and returned by legacy response shapes)."""
    live = _get_live_cycle()
    return live["quarter_label"] if live else ""


def _cycle_serialize(doc: dict) -> dict:
    doc = dict(doc)
    doc["id"] = str(doc.pop("_id", ""))
    for k in ("created_at", "updated_at"):
        if isinstance(doc.get(k), datetime):
            doc[k] = doc[k].isoformat()
    return doc


def _cycle_stats(quarter_id: str) -> dict:
    eligible = appraisal_eligibility_collection.count_documents({"quarter_id": quarter_id})
    submitted = appraisal_collection.count_documents({
        "quarter_id": quarter_id,
        "status": {"$in": ["submitted", "TL_approved", "TL_rejected", "PnD_approved", "PnD_rejected"]},
    })
    tl_approved = appraisal_collection.count_documents({
        "quarter_id": quarter_id,
        "status": {"$in": ["TL_approved", "PnD_approved", "PnD_rejected"]},
    })
    partner_approved = appraisal_collection.count_documents({"quarter_id": quarter_id, "status": "PnD_approved"})
    return {
        "eligible":        eligible,
        "submitted":       submitted,
        "tlApproved":      tl_approved,
        "partnerApproved": partner_approved,
        "pending":         max(submitted - tl_approved, 0),
    }


def _is_cycle_open() -> bool:
    """Whether the KRA submission window is currently open for employees —
    true exactly when a quarter is Live."""
    return _get_live_cycle() is not None


def _set_cycle_open(is_open: bool) -> None:
    """Legacy boolean toggle (kept for the /admin/cycle endpoint). Closing
    closes whichever quarter is live; opening has no effect here — use
    /admin/cycles/{quarter_id}/activate to choose which quarter goes live."""
    if not is_open:
        appraisal_cycles_collection.update_many(
            {"status": "live"}, {"$set": {"status": "closed", "updated_at": datetime.utcnow()}}
        )


def _check_eligibility(emp_id: str) -> dict:
    live = _get_live_cycle()
    if not live:
        return {
            "eligible": False,
            "reason":   "KRA appraisal is currently closed. No active appraisal cycle.",
            "doj": None, "one_year_date": None,
        }
    emp = employee_details_collection.find_one({"EmpID": emp_id.strip().upper()})
    if not emp:
        return {"eligible": False, "reason": "Employee record not found.", "doj": None, "one_year_date": None}
    elig = appraisal_eligibility_collection.find_one({
        "quarter_id":     live["quarter_id"],
        "employee_code":  emp_id.strip().upper(),
    })
    if not elig:
        return {
            "eligible": False,
            "reason":   f"KRA appraisal is currently closed/not applicable for you for {live['quarter_label']}.",
            "doj": None, "one_year_date": None,
        }
    return {"eligible": True, "reason": "", "doj": "", "one_year_date": ""}


def _parse_doj(raw) -> Optional[date]:
    if not raw:
        return None
    if isinstance(raw, (date, datetime)):
        return raw if isinstance(raw, date) else raw.date()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(str(raw).strip(), fmt).date()
        except ValueError:
            continue
    return None


def _serialize(doc: dict) -> dict:
    doc["id"] = str(doc.pop("_id", ""))
    if doc.get("selfScore") is None and doc.get("score") is not None:
        doc["selfScore"] = doc["score"]
    if doc.get("selfMaxScore") is None and doc.get("maxScore") is not None:
        doc["selfMaxScore"] = doc["maxScore"]
    if doc.get("selfPercentage") is None and doc.get("percentage") is not None:
        doc["selfPercentage"] = doc["percentage"]
    return doc


# ─────────────────────────────────────────────────────────────────────────────
# Access guards
# ─────────────────────────────────────────────────────────────────────────────

def _require_tl_or_above(current_user: str):
    role = _resolve_role(current_user)
    if role not in ("tl", "partner", "admin") and not _is_admin(current_user):
        raise HTTPException(403, "TL or Partner access required")
    return role


def _require_partner_or_above(current_user: str):
    """Allow: pure partner, pure admin, or admin+partner (senior partner)."""
    role     = _resolve_role(current_user)
    is_admin = _is_admin(current_user)
    if role not in ("partner", "admin") and not is_admin:
        raise HTTPException(403, "Partner access required")
    return role


def _require_admin(current_user: str):
    if not _is_admin(current_user):
        raise HTTPException(403, "Admin access required")


# ─────────────────────────────────────────────────────────────────────────────
# Routes — meta
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/period")
async def get_period(current_user: str = Depends(get_current_user)):
    live = _get_live_cycle()
    if not live:
        return {"period": "", "quarterId": None, "quarterLabel": None, "status": "closed"}
    return {
        "period":       live["quarter_label"],
        "quarterId":    live["quarter_id"],
        "quarterLabel": live["quarter_label"],
        "status":       "live",
    }


@router.get("/cycles")
async def list_cycles_public(current_user: str = Depends(get_current_user)):
    """Lightweight quarter list for the frontend's quarter switcher."""
    cycles = list(appraisal_cycles_collection.find(
        {}, {"quarter_id": 1, "quarter_label": 1, "status": 1}
    ).sort("created_at", -1))
    return {"success": True, "data": [
        {"quarter_id": c["quarter_id"], "quarter_label": c["quarter_label"], "status": c["status"]}
        for c in cycles
    ]}


@router.get("/my_role")
async def get_my_role(current_user: str = Depends(get_current_user)):
    """
    Returns resolved role + isAdmin flag.
    Frontend uses isAdmin to decide whether to show Analysis tab
    and Form/History/Status tabs for users who are partners in admin list.
    """
    role     = _resolve_role(current_user)
    is_admin = _is_admin(current_user)
    emp = employee_details_collection.find_one(
        {"EmpID": current_user.upper()},
        {"Emp Name": 1, "Designation Name": 1, "Grade Name": 1}
    )
    return {
        "role":        role,
        "isAdmin":     is_admin,   # ← NEW: frontend uses this for extra tabs
        "empId":       current_user.upper(),
        "name":        emp.get("Emp Name", "") if emp else "",
        "designation": emp.get("Designation Name", "") if emp else "",
    }


@router.get("/cycle_status")
async def get_cycle_status(current_user: str = Depends(get_current_user)):
    """Whether the KRA submission window is open. Visible to everyone."""
    live = _get_live_cycle()
    return {
        "success":   True,
        "open":      live is not None,
        "period":    live["quarter_label"] if live else "",
        "quarterId": live["quarter_id"] if live else None,
    }


@router.post("/admin/cycle")
async def set_cycle_status(data: CycleToggleRequest, current_user: str = Depends(get_current_user)):
    """Admin-only legacy quick action: close the live quarter. Opening a
    specific quarter is done via /admin/cycles/{quarter_id}/activate."""
    _require_admin(current_user)
    _set_cycle_open(data.open)
    return {
        "success": True,
        "open":    _is_cycle_open(),
        "message": f"KRA submission window {'opened' if data.open else 'closed'}.",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Routes — Quarter (Cycle) Management — Admin only
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/admin/cycles")
async def admin_list_cycles(current_user: str = Depends(get_current_user)):
    _require_admin(current_user)
    cycles = list(appraisal_cycles_collection.find({}).sort("created_at", -1))
    data = []
    for c in cycles:
        row = _cycle_serialize(c)
        row.update(_cycle_stats(c["quarter_id"]))
        data.append(row)
    return {"success": True, "data": data}


@router.post("/admin/cycles")
async def admin_create_cycle(data: CreateCycleRequest, current_user: str = Depends(get_current_user)):
    _require_admin(current_user)
    label = data.quarter_label.strip()
    if not label:
        raise HTTPException(400, "quarter_label is required")
    quarter_id = _slugify_quarter_id(label)
    if appraisal_cycles_collection.find_one({"quarter_id": quarter_id}):
        raise HTTPException(400, f"A quarter with label '{label}' already exists.")
    now = datetime.utcnow()
    doc = {
        "quarter_id":    quarter_id,
        "quarter_label": label,
        "status":        "draft",
        "created_at":    now,
        "created_by":    current_user.upper(),
        "updated_at":    now,
        "updated_by":    current_user.upper(),
    }
    appraisal_cycles_collection.insert_one(doc)
    result = _cycle_serialize(doc)
    result.update(_cycle_stats(quarter_id))
    return {"success": True, "data": result}


@router.put("/admin/cycles/{quarter_id}")
async def admin_update_cycle(quarter_id: str, data: UpdateCycleRequest, current_user: str = Depends(get_current_user)):
    _require_admin(current_user)
    cycle = _get_cycle(quarter_id)
    if not cycle:
        raise HTTPException(404, "Quarter not found")
    label = data.quarter_label.strip()
    if not label:
        raise HTTPException(400, "quarter_label is required")
    appraisal_cycles_collection.update_one(
        {"quarter_id": quarter_id},
        {"$set": {"quarter_label": label, "updated_at": datetime.utcnow(), "updated_by": current_user.upper()}},
    )
    return {"success": True}


@router.post("/admin/cycles/{quarter_id}/activate")
async def admin_activate_cycle(quarter_id: str, current_user: str = Depends(get_current_user)):
    _require_admin(current_user)
    cycle = _get_cycle(quarter_id)
    if not cycle:
        raise HTTPException(404, "Quarter not found")
    now = datetime.utcnow()
    previously_live = appraisal_cycles_collection.find_one({"status": "live", "quarter_id": {"$ne": quarter_id}})
    appraisal_cycles_collection.update_many(
        {"status": "live", "quarter_id": {"$ne": quarter_id}},
        {"$set": {"status": "closed", "updated_at": now, "updated_by": current_user.upper()}},
    )
    appraisal_cycles_collection.update_one(
        {"quarter_id": quarter_id},
        {"$set": {"status": "live", "updated_at": now, "updated_by": current_user.upper()}},
    )
    return {
        "success": True,
        "message": f"{cycle['quarter_label']} is now Live.",
        "closedPreviousQuarter": previously_live["quarter_label"] if previously_live else None,
    }


@router.post("/admin/cycles/{quarter_id}/close")
async def admin_close_cycle(quarter_id: str, current_user: str = Depends(get_current_user)):
    _require_admin(current_user)
    cycle = _get_cycle(quarter_id)
    if not cycle:
        raise HTTPException(404, "Quarter not found")
    stats = _cycle_stats(quarter_id)
    appraisal_cycles_collection.update_one(
        {"quarter_id": quarter_id},
        {"$set": {"status": "closed", "updated_at": datetime.utcnow(), "updated_by": current_user.upper()}},
    )
    return {"success": True, "message": f"{cycle['quarter_label']} closed.", "stats": stats}


_ELIGIBILITY_REQUIRED_COLUMNS = ["Employee Code", "Employee Name"]


@router.post("/admin/cycles/{quarter_id}/eligibility/upload")
async def admin_upload_eligibility(
    quarter_id: str,
    current_user: str = Depends(get_current_user),
    file: UploadFile = File(...),
):
    """Admin-only: uploads/replaces the HR-provided eligible-employee list
    for a quarter. Full replace — a re-upload discards the previous list
    for this quarter only; other quarters are untouched."""
    _require_admin(current_user)
    cycle = _get_cycle(quarter_id)
    if not cycle:
        raise HTTPException(404, "Quarter not found")

    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in ("xlsx", "xls", "csv"):
        raise HTTPException(400, f"Unsupported file type: .{ext}. Upload an Excel (.xlsx/.xls) or .csv file.")

    content = await file.read()
    try:
        df = pd.read_csv(io.BytesIO(content)) if ext == "csv" else pd.read_excel(io.BytesIO(content))
    except Exception as e:
        raise HTTPException(400, f"Could not read file: {e}")

    df.columns = [str(c).strip() for c in df.columns]
    missing = [c for c in _ELIGIBILITY_REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise HTTPException(400, f"Missing expected column(s): {', '.join(missing)}")

    total = len(df)
    seen_codes = set()
    valid_rows = []
    invalid_rows = []
    duplicate_count = 0

    for _, row in df.iterrows():
        raw_code = str(row.get("Employee Code", "") or "").strip()
        raw_name = str(row.get("Employee Name", "") or "").strip()
        code = raw_code.upper()
        if not code or code.upper() == "NAN":
            invalid_rows.append({"employeeCode": raw_code, "employeeName": raw_name, "reason": "Missing Employee Code"})
            continue
        if code in seen_codes:
            duplicate_count += 1
            invalid_rows.append({"employeeCode": raw_code, "employeeName": raw_name, "reason": "Duplicate Employee Code"})
            continue
        emp = employee_details_collection.find_one({"EmpID": code})
        if not emp:
            invalid_rows.append({"employeeCode": raw_code, "employeeName": raw_name, "reason": "Employee Code not found in employee master"})
            continue
        seen_codes.add(code)
        valid_rows.append({
            "quarter_id":     quarter_id,
            "employee_code":  code,
            "employee_name":  raw_name or emp.get("Emp Name", "") or emp.get("Name", ""),
        })

    now = datetime.utcnow()
    appraisal_eligibility_collection.delete_many({"quarter_id": quarter_id})
    if valid_rows:
        for r in valid_rows:
            r["uploaded_at"] = now
            r["uploaded_by"] = current_user.upper()
        appraisal_eligibility_collection.insert_many(valid_rows)

    appraisal_upload_history_collection.insert_one({
        "quarter_id":      quarter_id,
        "uploaded_by":     current_user.upper(),
        "uploaded_at":     now,
        "filename":        file.filename,
        "total_records":   total,
        "valid_count":     len(valid_rows),
        "invalid_count":   len(invalid_rows),
        "duplicate_count": duplicate_count,
        "invalid_rows":    invalid_rows,
    })

    appraisal_cycles_collection.update_one(
        {"quarter_id": quarter_id},
        {"$set": {"updated_at": now, "updated_by": current_user.upper()}},
    )

    return {
        "success":        True,
        "totalRecords":   total,
        "validEmployees": len(valid_rows),
        "invalidCount":   len(invalid_rows),
        "duplicateCount": duplicate_count,
        "invalidRows":    invalid_rows,
    }


@router.get("/admin/cycles/{quarter_id}/eligibility")
async def admin_list_eligibility(quarter_id: str, current_user: str = Depends(get_current_user)):
    _require_admin(current_user)
    rows = list(appraisal_eligibility_collection.find(
        {"quarter_id": quarter_id}, {"employee_code": 1, "employee_name": 1, "uploaded_at": 1}
    ).sort("employee_code", 1))
    data = []
    for r in rows:
        uploaded_at = r.get("uploaded_at")
        data.append({
            "employeeCode": r.get("employee_code", ""),
            "employeeName": r.get("employee_name", ""),
            "uploadedAt":   uploaded_at.isoformat() if isinstance(uploaded_at, datetime) else uploaded_at,
        })
    return {"success": True, "data": data}


# ─────────────────────────────────────────────────────────────────────────────
# Routes — employee (own KRA)
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/eligibility/{emp_id}")
async def check_eligibility(emp_id: str, current_user: str = Depends(get_current_user)):
    if emp_id.upper() != current_user.upper():
        raise HTTPException(403, "Unauthorized")
    return _check_eligibility(emp_id)


@router.get("/questions/{emp_id}")
async def get_questions(emp_id: str, current_user: str = Depends(get_current_user)):
    if emp_id.upper() != current_user.upper():
        raise HTTPException(403, "Unauthorized")
    elig = _check_eligibility(emp_id)
    if not elig["eligible"]:
        raise HTTPException(403, elig["reason"])
    emp         = employee_details_collection.find_one({"EmpID": emp_id.strip().upper()})
    designation = emp.get("Designation Name", "") if emp else ""
    return get_questions_for_employee(emp_id, designation)


@router.post("/save")
async def save_appraisal(data: AppraisalSaveRequest, current_user: str = Depends(get_current_user)):
    if data.employeeId.upper() != current_user.upper():
        raise HTTPException(403, "Unauthorized")
    live = _get_live_cycle()
    if not live:
        raise HTTPException(403, "KRA submission window is currently closed.")
    elig = _check_eligibility(data.employeeId)
    if not elig["eligible"]:
        raise HTTPException(403, elig["reason"])
    if data.status not in ("draft", "submitted"):
        raise HTTPException(400, "status must be 'draft' or 'submitted'")

    emp         = employee_details_collection.find_one({"EmpID": data.employeeId.strip().upper()})
    emp_id      = emp.get("EmpID", "") if emp else ""
    designation = emp.get("Designation Name", "") if emp else ""
    emp_name    = emp.get("Emp Name") or emp.get("Name") or "" if emp else ""
    partner     = emp.get("PartnerEmpCode") or "" if emp else ""
    partner_name= emp.get("Partner") or "" if emp else ""
    reporting   = emp.get("ReportingEmpCode") or "" if emp else ""
    reporting_name = emp.get("ReportingEmpName") or "" if emp else ""

    quarter_id = live["quarter_id"]
    period_val = live["quarter_label"]
    now_iso    = datetime.utcnow().isoformat()

    existing_submitted = appraisal_collection.find_one({
        "employeeId": data.employeeId.upper(),
        "quarter_id": quarter_id,
        "status":     {"$in": ["submitted", "TL_approved", "TL_rejected",
                                "PnD_approved", "PnD_rejected"]},
    })
    if existing_submitted:
        raise HTTPException(400, "Appraisal already submitted for this period.")

    scoring = calculate_score(emp_id, designation, data.answers)

    doc = {
        "employeeId":        data.employeeId.upper(),
        "employeeName":      emp_name,
        "designation":       designation,
        "partnerEmpCode":    partner,
        "partnerEmpName":    partner_name,
        "reportingEmpCode":  reporting,
        "reportingEmpName":  reporting_name,
        "quarter_id":        quarter_id,
        "period":            period_val,
        "answers":           data.answers,
        "status":            data.status,
        "score":             scoring["score"],
        "maxScore":          scoring["max_score"],
        "percentage":        scoring["percentage"],
        "selfScore":         scoring["score"],
        "selfMaxScore":      scoring["max_score"],
        "selfPercentage":    scoring["percentage"],
        "tl_responses":      None,
        "tlScore":           None,
        "tlMaxScore":        None,
        "tlPercentage":      None,
        "pnd_responses":     None,
        "pndScore":          None,
        "pndMaxScore":       None,
        "pndPercentage":     None,
        "questionSource":    scoring.get("source", "none"),
        "updatedAt":         now_iso,
    }

    existing_draft = appraisal_collection.find_one({
        "employeeId": data.employeeId.upper(),
        "quarter_id": quarter_id,
        "status":     "draft",
    })
    if existing_draft:
        appraisal_collection.update_one({"_id": existing_draft["_id"]}, {"$set": doc})
        record_id = str(existing_draft["_id"])
    else:
        doc["createdAt"] = now_iso
        result    = appraisal_collection.insert_one(doc)
        record_id = str(result.inserted_id)

    return {
        "success": True,
        "message": "KRA submitted!" if data.status == "submitted" else "Draft saved.",
        "id":      record_id,
        "status":  data.status,
    }


@router.get("/my/{emp_id}")
async def get_my_appraisals(emp_id: str, current_user: str = Depends(get_current_user)):
    if emp_id.upper() != current_user.upper():
        raise HTTPException(403, "Unauthorized")
    records = list(appraisal_collection.find(
        {"employeeId": emp_id.upper()},
        {"_id": 1, "period": 1, "quarter_id": 1, "status": 1, "updatedAt": 1,
         "createdAt": 1, "answers": 1, "designation": 1}
    ))
    result = []
    for r in records:
        result.append({
            "id":          str(r["_id"]),
            "period":      r.get("period"),
            "quarterId":   r.get("quarter_id"),
            "status":      r.get("status"),
            "designation": r.get("designation"),
            "answers":     r.get("answers", {}),
            "updatedAt":   r.get("updatedAt"),
            "createdAt":   r.get("createdAt"),
        })
    return {"success": True, "data": result}


@router.get("/status/{emp_id}")
async def get_appraisal_status(emp_id: str, current_user: str = Depends(get_current_user)):
    if emp_id.upper() != current_user.upper():
        raise HTTPException(403, "Unauthorized")
    live = _get_live_cycle()
    p = live["quarter_label"] if live else ""
    record = None
    if live:
        record = appraisal_collection.find_one(
            {"employeeId": emp_id.upper(), "quarter_id": live["quarter_id"]},
            sort=[("updatedAt", -1)]
        )
    if not record:
        return {"success": True, "status": "not_started", "period": p, "id": None, "answers": {}}
    return {
        "success":   True,
        "status":    record.get("status"),
        "period":    p,
        "id":        str(record["_id"]),
        "updatedAt": record.get("updatedAt"),
        "answers":   record.get("answers", {}),
    }


@router.get("/my_status_detail/{emp_id}")
async def get_my_status_detail(emp_id: str, current_user: str = Depends(get_current_user)):
    if emp_id.upper() != current_user.upper():
        raise HTTPException(403, "Unauthorized")

    live = _get_live_cycle()
    p = live["quarter_label"] if live else ""
    record = None
    if live:
        record = appraisal_collection.find_one(
            {"employeeId": emp_id.upper(), "quarter_id": live["quarter_id"]},
            sort=[("updatedAt", -1)]
        )

    emp = employee_details_collection.find_one({"EmpID": emp_id.strip().upper()})
    tl_code      = emp.get("ReportingEmpCode", "") if emp else ""
    tl_name      = emp.get("ReportingEmpName", "") if emp else ""
    partner_code = emp.get("PartnerEmpCode",   "") if emp else ""
    partner_name = emp.get("Partner",          "") if emp else ""

    tl_is_partner = tl_code and partner_code and tl_code.upper() == partner_code.upper()

    if not record:
        return {
            "success":          True,
            "period":           p,
            "status":           "not_started",
            "tlIsSameAsPartner": tl_is_partner,
            "levels":           _build_pipeline(None, tl_name, partner_name, tl_is_partner),
        }

    status = record.get("status", "not_started")
    return {
        "success":           True,
        "period":            p,
        "status":            status,
        "selfPercentage":    record.get("selfPercentage") or record.get("percentage"),
        "tlPercentage":      record.get("tlPercentage"),
        "pndPercentage":     record.get("pndPercentage"),
        "tlActionBy":        record.get("tlActionBy", tl_name),
        "pndActionBy":       record.get("pndActionBy", partner_name),
        "tlActionAt":        record.get("tlActionAt"),
        "pndActionAt":       record.get("pndActionAt"),
        "tlRemarks":         record.get("tlRemarks", ""),
        "pndRemarks":        record.get("pndRemarks", ""),
        "tlIsSameAsPartner": tl_is_partner,
        "updatedAt":         record.get("updatedAt"),
        "levels":            _build_pipeline(status, tl_name, partner_name, tl_is_partner),
    }


def _build_pipeline(status, tl_name, partner_name, tl_is_partner):
    STATUS_ORDER = [
        "not_started", "draft", "submitted",
        "TL_approved", "TL_rejected",
        "PnD_approved", "PnD_rejected",
    ]

    def _step_state(required_status, rejected_status=None):
        if status is None or status == "not_started":
            return "pending"
        if rejected_status and status == rejected_status:
            return "rejected"
        idx_current  = STATUS_ORDER.index(status) if status in STATUS_ORDER else 0
        idx_required = STATUS_ORDER.index(required_status) if required_status in STATUS_ORDER else 99
        if idx_current >= idx_required:
            return "done"
        if idx_current == idx_required - 1:
            return "active"
        return "pending"

    levels = [
        {"label": "Self Submission", "actor": "You",           "state": _step_state("submitted")},
        {"label": "TL Approval",     "actor": tl_name or "TL", "state": _step_state("TL_approved", "TL_rejected")},
    ]
    if not tl_is_partner:
        levels.append(
            {"label": "Partner Approval", "actor": partner_name or "Partner",
             "state": _step_state("PnD_approved", "PnD_rejected")}
        )
    return levels


# ─────────────────────────────────────────────────────────────────────────────
# Routes — TL / Manager
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/tl/pending")
async def tl_pending(quarter_id: Optional[str] = None, current_user: str = Depends(get_current_user)):
    _require_tl_or_above(current_user)
    qid = _resolve_quarter_id(quarter_id)
    if not qid:
        return {"success": True, "data": []}
    emps = _employees_under_tl(current_user)
    emp_ids = [e["EmpID"].upper() for e in emps]
    records = list(appraisal_collection.find({
        "employeeId": {"$in": emp_ids},
        "quarter_id": qid,
        "status":     "submitted",
    }, {"_id": 1, "employeeId": 1, "employeeName": 1, "designation": 1,
        "status": 1, "updatedAt": 1, "selfPercentage": 1, "percentage": 1, "score": 1, "maxScore": 1}))
    return {"success": True, "data": [_serialize(r) for r in records]}


@router.get("/tl/approved")
async def tl_approved(quarter_id: Optional[str] = None, current_user: str = Depends(get_current_user)):
    _require_tl_or_above(current_user)
    qid = _resolve_quarter_id(quarter_id)
    if not qid:
        return {"success": True, "data": []}
    emps = _employees_under_tl(current_user)
    emp_ids = [e["EmpID"].upper() for e in emps]
    records = list(appraisal_collection.find({
        "employeeId": {"$in": emp_ids},
        "quarter_id": qid,
        "status":     "TL_approved",
    }, {"_id": 1, "employeeId": 1, "employeeName": 1, "designation": 1,
        "status": 1, "updatedAt": 1, "selfPercentage": 1, "tlPercentage": 1,
        "tl_responses": 1, "answers": 1, "percentage": 1, "score": 1, "maxScore": 1}))
    return {"success": True, "data": [_serialize(r) for r in records]}


@router.get("/tl/rejected")
async def tl_rejected(quarter_id: Optional[str] = None, current_user: str = Depends(get_current_user)):
    _require_tl_or_above(current_user)
    qid = _resolve_quarter_id(quarter_id)
    if not qid:
        return {"success": True, "data": []}
    emps = _employees_under_tl(current_user)
    emp_ids = [e["EmpID"].upper() for e in emps]
    records = list(appraisal_collection.find({
        "employeeId": {"$in": emp_ids},
        "quarter_id": qid,
        "status":     "TL_rejected",
    }, {"_id": 1, "employeeId": 1, "employeeName": 1, "designation": 1,
        "status": 1, "updatedAt": 1, "selfPercentage": 1, "tlPercentage": 1,
        "tl_responses": 1, "answers": 1, "percentage": 1, "score": 1, "maxScore": 1}))
    return {"success": True, "data": [_serialize(r) for r in records]}


@router.get("/tl/record/{record_id}")
async def tl_get_record(record_id: str, current_user: str = Depends(get_current_user)):
    _require_tl_or_above(current_user)
    try:
        oid = ObjectId(record_id)
    except Exception:
        raise HTTPException(400, "Invalid record id")
    record = appraisal_collection.find_one({"_id": oid})
    if not record:
        raise HTTPException(404, "Record not found")

    role = _resolve_role(current_user)
    if role == "tl":
        emps    = _employees_under_tl(current_user)
        emp_ids = [e["EmpID"].upper() for e in emps]
        if record["employeeId"].upper() not in emp_ids:
            raise HTTPException(403, "Not your employee")

    emp         = employee_details_collection.find_one({"EmpID": record["employeeId"].upper()})
    designation = emp.get("Designation Name", "") if emp else ""
    questions   = get_questions_for_employee(record["employeeId"], designation)

    result = _serialize(record)
    result["questions"] = questions
    return {"success": True, "data": result}


@router.post("/tl/action/{record_id}")
async def tl_action(
    record_id: str,
    data: AppraisalReviewRequest,
    current_user: str = Depends(get_current_user)
):
    _require_tl_or_above(current_user)
    if data.action not in ("approve", "reject"):
        raise HTTPException(400, "action must be 'approve' or 'reject'")

    try:
        oid = ObjectId(record_id)
    except Exception:
        raise HTTPException(400, "Invalid record id")

    record = appraisal_collection.find_one({"_id": oid})
    if not record:
        raise HTTPException(404, "Record not found")
    if record["status"] not in ("submitted", "TL_rejected"):
        raise HTTPException(400, f"Cannot action a record with status '{record['status']}'")

    record_quarter_id = record.get("quarter_id")
    if record_quarter_id:
        rec_cycle = _get_cycle(record_quarter_id)
        if not rec_cycle or rec_cycle.get("status") != "live":
            raise HTTPException(403, "This quarter is closed; approvals are disabled.")

    role = _resolve_role(current_user)
    if role == "tl":
        emps    = _employees_under_tl(current_user)
        emp_ids = [e["EmpID"].upper() for e in emps]
        if record["employeeId"].upper() not in emp_ids:
            raise HTTPException(403, "Not your employee")

    new_status = "TL_approved" if data.action == "approve" else "TL_rejected"
    now_iso    = datetime.utcnow().isoformat()

    update = {
        "status":     new_status,
        "tlActionBy": current_user.upper(),
        "tlActionAt": now_iso,
        "updatedAt":  now_iso,
    }

    if data.tl_responses:
        emp         = employee_details_collection.find_one({"EmpID": record["employeeId"].upper()})
        designation = emp.get("Designation Name", "") if emp else ""
        tl_scoring  = calculate_score(record["employeeId"], designation, data.tl_responses)
        update["tl_responses"] = data.tl_responses
        update["tlScore"]      = tl_scoring["score"]
        update["tlMaxScore"]   = tl_scoring["max_score"]
        update["tlPercentage"] = tl_scoring["percentage"]
    else:
        update["tl_responses"] = record.get("answers", {})
        update["tlScore"]      = record.get("selfScore")      or record.get("score")
        update["tlMaxScore"]   = record.get("selfMaxScore")   or record.get("maxScore")
        update["tlPercentage"] = record.get("selfPercentage") or record.get("percentage")

    if data.remarks:
        update["tlRemarks"] = data.remarks

    appraisal_collection.update_one({"_id": oid}, {"$set": update})
    return {"success": True, "message": f"Record {new_status}", "status": new_status}


# ─────────────────────────────────────────────────────────────────────────────
# Routes — Partner / Director (PnD)
# ─────────────────────────────────────────────────────────────────────────────

# def _pnd_pending_employees(partner_id: str, p: str):
#     emps     = _employees_under_partner(partner_id)
#     emp_ids  = [e["EmpID"].upper() for e in emps]
#     tl_codes = set(e.get("ReportingEmpCode", "").upper() for e in emps if e.get("ReportingEmpCode"))
#     emp_ids_excl_tls = [eid for eid in emp_ids if eid not in tl_codes]
#     records = list(appraisal_collection.find({
#         "employeeId": {"$in": emp_ids_excl_tls},
#         "period":     p,
#         "status":     "TL_approved",
#     }, {"_id": 1, "employeeId": 1, "employeeName": 1, "designation": 1,
#         "status": 1, "updatedAt": 1, "selfPercentage": 1, "tlPercentage": 1,
#         "percentage": 1, "score": 1, "maxScore": 1}))
#     return [_serialize(r) for r in records]

def _pnd_pending_employees(partner_id: str, qid: str):
    emps     = _employees_under_partner(partner_id)
    emp_ids  = [e["EmpID"].upper() for e in emps]
    tl_codes = set(
        e.get("ReportingEmpCode", "").upper()
        for e in emps if e.get("ReportingEmpCode")
    )
    emp_ids_excl_tls = [eid for eid in emp_ids if eid not in tl_codes]

    # Employees whose TL IS the partner themselves — no separate TL step needed
    direct_ids = [
        e["EmpID"].upper() for e in emps
        if e.get("ReportingEmpCode", "").upper() == partner_id.strip().upper()
        and e["EmpID"].upper() not in tl_codes
    ]
    # Everyone else must pass through TL approval first
    indirect_ids = [eid for eid in emp_ids_excl_tls if eid not in direct_ids]

    projection = {
        "_id": 1, "employeeId": 1, "employeeName": 1, "designation": 1,
        "status": 1, "updatedAt": 1, "selfPercentage": 1, "tlPercentage": 1,
        "percentage": 1, "score": 1, "maxScore": 1,
    }

    records = []
    if direct_ids:
        records += list(appraisal_collection.find(
            {"employeeId": {"$in": direct_ids}, "quarter_id": qid, "status": "submitted"},
            projection
        ))
    if indirect_ids:
        records += list(appraisal_collection.find(
            {"employeeId": {"$in": indirect_ids}, "quarter_id": qid, "status": "TL_approved"},
            projection
        ))

    return [_serialize(r) for r in records]


# def _pnd_pending_tls(partner_id: str, p: str):
#     tl_codes = _tls_under_partner(partner_id)
#     records = list(appraisal_collection.find({
#         "employeeId": {"$in": tl_codes},
#         "period":     p,
#         "status":     "submitted",
#     }, {"_id": 1, "employeeId": 1, "employeeName": 1, "designation": 1,
#         "status": 1, "updatedAt": 1, "selfPercentage": 1, "percentage": 1, "score": 1, "maxScore": 1}))
#     return [_serialize(r) for r in records]

def _pnd_pending_tls(partner_id: str, qid: str):
    tl_codes = _tls_under_partner(partner_id)
    records = list(appraisal_collection.find({
        "employeeId": {"$in": tl_codes},
        "quarter_id": qid,
        "status":     {"$in": ["submitted", "TL_approved"]},  # ← add TL_approved
    }, {"_id": 1, "employeeId": 1, "employeeName": 1, "designation": 1,
        "status": 1, "updatedAt": 1, "selfPercentage": 1, "tlPercentage": 1,
        "percentage": 1, "score": 1, "maxScore": 1}))
    return [_serialize(r) for r in records]


@router.get("/pnd/pending")
async def pnd_pending(quarter_id: Optional[str] = None, current_user: str = Depends(get_current_user)):
    _require_partner_or_above(current_user)
    qid = _resolve_quarter_id(quarter_id)
    if not qid:
        return {"success": True, "employees": [], "tls": []}
    return {
        "success":   True,
        "employees": _pnd_pending_employees(current_user, qid),
        "tls":       _pnd_pending_tls(current_user, qid),
    }


@router.get("/pnd/approved")
async def pnd_approved(quarter_id: Optional[str] = None, current_user: str = Depends(get_current_user)):
    _require_partner_or_above(current_user)
    qid = _resolve_quarter_id(quarter_id)
    if not qid:
        return {"success": True, "employees": [], "tls": []}
    emps    = _employees_under_partner(current_user)
    all_ids = [e["EmpID"].upper() for e in emps]
    tl_ids  = set(_tls_under_partner(current_user))
    emp_ids = [eid for eid in all_ids if eid not in tl_ids]

    emp_records = list(appraisal_collection.find({
        "employeeId": {"$in": emp_ids},
        "quarter_id": qid,
        "status":     "PnD_approved",
    }, {"_id": 1, "employeeId": 1, "employeeName": 1, "designation": 1,
        "status": 1, "updatedAt": 1, "selfPercentage": 1,
        "tlPercentage": 1, "pndPercentage": 1,
        "tl_responses": 1, "pnd_responses": 1, "answers": 1, "percentage": 1, "score": 1, "maxScore": 1}))

    tl_records = list(appraisal_collection.find({
        "employeeId": {"$in": list(tl_ids)},
        "quarter_id": qid,
        "status":     "PnD_approved",
    }, {"_id": 1, "employeeId": 1, "employeeName": 1, "designation": 1,
        "status": 1, "updatedAt": 1, "selfPercentage": 1,
        "tlPercentage": 1, "pndPercentage": 1,
        "tl_responses": 1, "pnd_responses": 1, "answers": 1, "percentage": 1, "score": 1, "maxScore": 1}))

    return {
        "success":   True,
        "employees": [_serialize(r) for r in emp_records],
        "tls":       [_serialize(r) for r in tl_records],
    }


@router.get("/pnd/rejected")
async def pnd_rejected(quarter_id: Optional[str] = None, current_user: str = Depends(get_current_user)):
    _require_partner_or_above(current_user)
    qid = _resolve_quarter_id(quarter_id)
    if not qid:
        return {"success": True, "employees": [], "tls": []}
    emps    = _employees_under_partner(current_user)
    all_ids = [e["EmpID"].upper() for e in emps]
    tl_ids  = set(_tls_under_partner(current_user))
    emp_ids = [eid for eid in all_ids if eid not in tl_ids]

    emp_records = list(appraisal_collection.find({
        "employeeId": {"$in": emp_ids},
        "quarter_id": qid,
        "status":     "PnD_rejected",
    }, {"_id": 1, "employeeId": 1, "employeeName": 1, "designation": 1,
        "status": 1, "updatedAt": 1, "selfPercentage": 1,
        "tlPercentage": 1, "pndPercentage": 1,
        "tl_responses": 1, "pnd_responses": 1, "answers": 1, "percentage": 1, "score": 1, "maxScore": 1}))

    tl_records = list(appraisal_collection.find({
        "employeeId": {"$in": list(tl_ids)},
        "quarter_id": qid,
        "status":     "PnD_rejected",
    }, {"_id": 1, "employeeId": 1, "employeeName": 1, "designation": 1,
        "status": 1, "updatedAt": 1, "selfPercentage": 1,
        "tlPercentage": 1, "pndPercentage": 1,
        "tl_responses": 1, "pnd_responses": 1, "answers": 1, "percentage": 1, "score": 1, "maxScore": 1}))

    return {
        "success":   True,
        "employees": [_serialize(r) for r in emp_records],
        "tls":       [_serialize(r) for r in tl_records],
    }


@router.get("/pnd/record/{record_id}")
async def pnd_get_record(record_id: str, current_user: str = Depends(get_current_user)):
    _require_partner_or_above(current_user)
    try:
        oid = ObjectId(record_id)
    except Exception:
        raise HTTPException(400, "Invalid record id")
    record = appraisal_collection.find_one({"_id": oid})
    if not record:
        raise HTTPException(404, "Record not found")

    emp         = employee_details_collection.find_one({"EmpID": record["employeeId"].upper()})
    designation = emp.get("Designation Name", "") if emp else ""
    questions   = get_questions_for_employee(record["employeeId"], designation)

    result = _serialize(record)
    result["questions"] = questions
    return {"success": True, "data": result}


@router.post("/pnd/action/{record_id}")
async def pnd_action(
    record_id: str,
    data: AppraisalReviewRequest,
    current_user: str = Depends(get_current_user)
):
    _require_partner_or_above(current_user)
    if data.action not in ("approve", "reject"):
        raise HTTPException(400, "action must be 'approve' or 'reject'")

    try:
        oid = ObjectId(record_id)
    except Exception:
        raise HTTPException(400, "Invalid record id")

    record = appraisal_collection.find_one({"_id": oid})
    if not record:
        raise HTTPException(404, "Record not found")

    allowed_statuses = ("TL_approved", "submitted", "PnD_rejected")
    if record["status"] not in allowed_statuses:
        raise HTTPException(400, f"Cannot action record with status '{record['status']}'")

    record_quarter_id = record.get("quarter_id")
    if record_quarter_id:
        rec_cycle = _get_cycle(record_quarter_id)
        if not rec_cycle or rec_cycle.get("status") != "live":
            raise HTTPException(403, "This quarter is closed; approvals are disabled.")

    new_status = "PnD_approved" if data.action == "approve" else "PnD_rejected"
    now_iso    = datetime.utcnow().isoformat()

    update = {
        "status":      new_status,
        "pndActionBy": current_user.upper(),
        "pndActionAt": now_iso,
        "updatedAt":   now_iso,
    }

    if data.pnd_responses:
        emp         = employee_details_collection.find_one({"EmpID": record["employeeId"].upper()})
        designation = emp.get("Designation Name", "") if emp else ""
        pnd_scoring = calculate_score(record["employeeId"], designation, data.pnd_responses)
        update["pnd_responses"] = data.pnd_responses
        update["pndScore"]      = pnd_scoring["score"]
        update["pndMaxScore"]   = pnd_scoring["max_score"]
        update["pndPercentage"] = pnd_scoring["percentage"]
    else:
        tl_resp = record.get("tl_responses") or record.get("answers", {})
        update["pnd_responses"] = tl_resp
        update["pndScore"]      = record.get("tlScore")      or record.get("selfScore")      or record.get("score")
        update["pndMaxScore"]   = record.get("tlMaxScore")   or record.get("selfMaxScore")   or record.get("maxScore")
        update["pndPercentage"] = record.get("tlPercentage") or record.get("selfPercentage") or record.get("percentage")

    # ← ADD HERE: mirror self→tl fields when TL == Partner (record arrived as "submitted")
    if record["status"] == "submitted" and not data.pnd_responses:
        update.setdefault("tlScore",      record.get("selfScore")      or record.get("score"))
        update.setdefault("tlMaxScore",   record.get("selfMaxScore")   or record.get("maxScore"))
        update.setdefault("tlPercentage", record.get("selfPercentage") or record.get("percentage"))
        
    if data.remarks:
        update["pndRemarks"] = data.remarks

    appraisal_collection.update_one({"_id": oid}, {"$set": update})
    return {"success": True, "message": f"Record {new_status}", "status": new_status}

# ─────────────────────────────────────────────────────────────────────────────
# Routes — Admin only
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/admin/pending")
async def admin_pending(quarter_id: Optional[str] = None, current_user: str = Depends(get_current_user)):
    _require_admin(current_user)
    qid = _resolve_quarter_id(quarter_id)
    if not qid:
        return {"success": True, "data": []}
    records = list(appraisal_collection.find(
        {"quarter_id": qid, "status": {"$in": ["submitted", "TL_approved"]}},
        {"_id": 1, "employeeId": 1, "employeeName": 1, "designation": 1,
         "status": 1, "updatedAt": 1, "selfPercentage": 1, "tlPercentage": 1,
         "reportingEmpCode": 1, "partnerEmpCode": 1, "percentage": 1, "score": 1, "maxScore": 1}
    ))
    return {"success": True, "data": [_serialize(r) for r in records]}


@router.get("/admin/approved")
async def admin_approved(quarter_id: Optional[str] = None, current_user: str = Depends(get_current_user)):
    _require_admin(current_user)
    qid = _resolve_quarter_id(quarter_id)
    if not qid:
        return {"success": True, "data": []}
    records = list(appraisal_collection.find(
        {"quarter_id": qid, "status": "PnD_approved"},
        {"_id": 1, "employeeId": 1, "employeeName": 1, "designation": 1,
         "status": 1, "updatedAt": 1, "selfPercentage": 1,
         "tlPercentage": 1, "pndPercentage": 1,
         "reportingEmpCode": 1, "partnerEmpCode": 1, "partnerEmpName": 1,
         "percentage": 1, "score": 1, "maxScore": 1}
    ))
    return {"success": True, "data": [_serialize(r) for r in records]}


@router.get("/admin/rejected")
async def admin_rejected(quarter_id: Optional[str] = None, current_user: str = Depends(get_current_user)):
    _require_admin(current_user)
    qid = _resolve_quarter_id(quarter_id)
    if not qid:
        return {"success": True, "data": []}
    records = list(appraisal_collection.find(
        {"quarter_id": qid, "status": {"$in": ["TL_rejected", "PnD_rejected"]}},
        {"_id": 1, "employeeId": 1, "employeeName": 1, "designation": 1,
         "status": 1, "updatedAt": 1, "selfPercentage": 1, "tlPercentage": 1,
         "reportingEmpCode": 1, "partnerEmpCode": 1, "percentage": 1, "score": 1, "maxScore": 1}
    ))
    return {"success": True, "data": [_serialize(r) for r in records]}


# ─────────────────────────────────────────────────────────────────────────────
# Routes — Analysis (admin + partner, both see full company data)
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/analysis")
async def get_analysis(quarter_id: Optional[str] = None, current_user: str = Depends(get_current_user)):
    """
    Analysis is accessible to:
      - Pure admin  → full company data
      - Partner     → full company data IF they are also in admin list
      - Partner     → only their own employees if NOT in admin list
    """
    role     = _resolve_role(current_user)
    is_admin = _is_admin(current_user)

    # Access check: must be partner, admin, or admin+partner
    # if role not in ("partner", "admin") and not is_admin:
    #     raise HTTPException(403, "Admin or Partner access required")

    if not is_admin and role != "admin":
        raise HTTPException(403, "Admin access required for Analysis")

    qid = _resolve_quarter_id(quarter_id)
    cycle = _get_cycle(qid) if qid else None
    p = cycle["quarter_label"] if cycle else ""
    if not qid:
        return {
            "success": True, "period": "", "totalApproved": 0,
            "top5Overall": [], "top5ByPartner": {}, "avgScores": {"self": None, "tl": None, "pnd": None},
            "designationBreakdown": {}, "scoreVariance": [],
            "pipeline": {"pending": 0, "tlApproved": 0, "tlRejected": 0, "pndApproved": 0, "pndRejected": 0},
            "tlWise": {}, "pndWise": {},
        }

    # ── KEY LOGIC ──
    # If user is admin (even if also partner) → NO filter, see all company data
    # If pure partner (not in admin list)     → filter by their partnerEmpCode
    if is_admin:
        # Full company-wide queries — no partner filter
        approved_query    = {"quarter_id": qid, "status": "PnD_approved"}
        all_period_query  = {"quarter_id": qid}
    else:
        # Pure partner — only their employees
        approved_query    = {"quarter_id": qid, "status": "PnD_approved", "partnerEmpCode": current_user.upper()}
        all_period_query  = {"quarter_id": qid, "partnerEmpCode": current_user.upper()}

    records = list(appraisal_collection.find(approved_query, {
        "_id": 1, "employeeId": 1, "employeeName": 1, "designation": 1,
        "partnerEmpCode": 1, "partnerEmpName": 1,
        "selfPercentage": 1, "tlPercentage": 1, "pndPercentage": 1,
        "selfScore": 1, "tlScore": 1, "pndScore": 1,
        "selfMaxScore": 1, "percentage": 1, "score": 1, "maxScore": 1,
    }))

    # ── Backfill selfPercentage and partner info for old approved documents ──
    # Old documents may be missing selfPercentage, partnerEmpCode, partnerEmpName.
    # One bulk query covers all gaps — no per-row DB calls.
    approved_ids_needing_enrich = [
        r["employeeId"] for r in records
        if r.get("selfPercentage") is None
        or not r.get("partnerEmpCode")
        or not r.get("partnerEmpName")
    ]
    approved_emp_lookup: dict = {}
    if approved_ids_needing_enrich:
        for emp in employee_details_collection.find(
            {"EmpID": {"$in": [e.upper() for e in approved_ids_needing_enrich]}},
            {"EmpID": 1, "PartnerEmpCode": 1, "Partner": 1}
        ):
            approved_emp_lookup[emp["EmpID"].upper()] = emp

    for r in records:
        if r.get("selfPercentage") is None:
            r["selfPercentage"] = r.get("percentage") or r.get("score")
        emp_data = approved_emp_lookup.get(r["employeeId"].upper(), {})
        if not r.get("partnerEmpCode"):
            r["partnerEmpCode"] = emp_data.get("PartnerEmpCode", "") or ""
        if not r.get("partnerEmpName"):
            # Try employee_details, then legacy "partner" field stored in appraisal doc
            r["partnerEmpName"] = (emp_data.get("Partner", "") or
                                   r.get("partner", "") or "")

    # 1. Overall top 5
    sorted_all  = sorted(records, key=lambda r: r.get("pndPercentage") or 0, reverse=True)
    top5_overall = [
        {
            "employeeId":   r["employeeId"],
            "employeeName": r.get("employeeName", ""),
            "designation":  r.get("designation", ""),
            "selfPct":      r.get("selfPercentage"),
            "tlPct":        r.get("tlPercentage"),
            "pndPct":       r.get("pndPercentage"),
        }
        for r in sorted_all[:5]
    ]

    # 2. Per-partner top 5
    partner_groups: dict[str, list] = {}
    for r in records:
        pk  = (r.get("partnerEmpCode") or "").strip() or "Unknown"
        pn  = (r.get("partnerEmpName") or "").strip() or pk
        key = f"{pk}|{pn}"
        if key not in partner_groups:
            partner_groups[key] = []
        partner_groups[key].append(r)

    pnd_top5 = {}
    for key, recs in partner_groups.items():
        pk, pn = key.split("|", 1)
        sorted_g = sorted(recs, key=lambda r: r.get("pndPercentage") or 0, reverse=True)
        pnd_top5[pk] = {
            "partnerName": pn,
            "top5": [
                {
                    "employeeId":   r["employeeId"],
                    "employeeName": r.get("employeeName", ""),
                    "designation":  r.get("designation", ""),
                    "selfPct":      r.get("selfPercentage"),
                    "tlPct":        r.get("tlPercentage"),
                    "pndPct":       r.get("pndPercentage"),
                }
                for r in sorted_g[:5]
            ]
        }

    # 3. Average scores
    def _avg(lst):
        lst = [x for x in lst if x is not None]
        return round(sum(lst) / len(lst), 2) if lst else None

    avg_self = _avg([r.get("selfPercentage") for r in records])
    avg_tl   = _avg([r.get("tlPercentage")   for r in records])
    avg_pnd  = _avg([r.get("pndPercentage")  for r in records])

    # 4. Designation breakdown
    desig_counts: dict[str, int] = {}
    for r in records:
        d = r.get("designation", "Unknown")
        desig_counts[d] = desig_counts.get(d, 0) + 1

    # 5. Score variance (self vs final)
    inflation = []
    for r in records:
        sp = r.get("selfPercentage") or r.get("percentage")
        pp = r.get("pndPercentage")
        if sp is not None and pp is not None:
            inflation.append({
                "employeeId":   r["employeeId"],
                "employeeName": r.get("employeeName", ""),
                "selfPct":      sp,
                "pndPct":       pp,
                "delta":        round(pp - sp, 2),
            })
    inflation_sorted = sorted(inflation, key=lambda x: abs(x["delta"]), reverse=True)[:10]

    # 6. Pipeline counts — all records this period
    all_records = list(appraisal_collection.find(all_period_query, {
        "_id": 1, "employeeId": 1, "employeeName": 1, "designation": 1,
        "status": 1, "reportingEmpCode": 1, "reportingEmpName": 1,
        "partnerEmpCode": 1, "partnerEmpName": 1,
        # Legacy field names used in old documents
        "partner": 1, "reportingManager": 1,
        "selfPercentage": 1, "tlPercentage": 1, "pndPercentage": 1,
        "percentage": 1, "score": 1,
    }))

    # ── Backfill missing TL/partner fields from employee_details for old documents ──
    # Old documents may not have reportingEmpCode/Name or partnerEmpCode/Name stored.
    # We fetch them in one bulk query and patch in-memory (no DB writes needed).
    needs_enrichment = [
        r["employeeId"] for r in all_records
        if not r.get("reportingEmpCode") or not r.get("partnerEmpCode")
           or not r.get("reportingEmpName") or not r.get("partnerEmpName")
    ]
    emp_lookup: dict = {}
    if needs_enrichment:
        for emp in employee_details_collection.find(
            {"EmpID": {"$in": [e.upper() for e in needs_enrichment]}},
            {"EmpID": 1, "ReportingEmpCode": 1, "ReportingEmpName": 1,
             "PartnerEmpCode": 1, "Partner": 1}
        ):
            emp_lookup[emp["EmpID"].upper()] = emp

    for r in all_records:
        emp_data = emp_lookup.get(r["employeeId"].upper(), {})
        if not r.get("reportingEmpCode"):
            r["reportingEmpCode"] = emp_data.get("ReportingEmpCode", "") or ""
        if not r.get("reportingEmpName"):
            # Try employee_details first, then fall back to legacy "reportingManager" field
            r["reportingEmpName"] = (emp_data.get("ReportingEmpName", "") or
                                     r.get("reportingManager", "") or "")
        if not r.get("partnerEmpCode"):
            r["partnerEmpCode"] = emp_data.get("PartnerEmpCode", "") or ""
        if not r.get("partnerEmpName"):
            # Try employee_details first, then fall back to legacy "partner" field
            r["partnerEmpName"] = (emp_data.get("Partner", "") or
                                   r.get("partner", "") or "")
        # Also backfill selfPercentage from legacy fields
        if r.get("selfPercentage") is None:
            r["selfPercentage"] = r.get("percentage") or r.get("score")

    pipeline_counts = {
        "pending":     sum(1 for r in all_records if r.get("status") == "submitted"),
        "tlApproved":  sum(1 for r in all_records if r.get("status") == "TL_approved"),
        "tlRejected":  sum(1 for r in all_records if r.get("status") == "TL_rejected"),
        "pndApproved": sum(1 for r in all_records if r.get("status") == "PnD_approved"),
        "pndRejected": sum(1 for r in all_records if r.get("status") == "PnD_rejected"),
    }

    # 7. TL-wise breakdown
    tl_wise: dict = {}
    for r in all_records:
        tl_code = (r.get("reportingEmpCode") or "").strip() or "Unknown"
        tl_name = (r.get("reportingEmpName") or "").strip() or tl_code
        if tl_code not in tl_wise:
            tl_wise[tl_code] = {
                "name": tl_name, "total": 0,
                "pending": 0, "tlApproved": 0, "tlRejected": 0,
                "approved": 0, "rejected": 0, "employees": []
            }
        st = r.get("status", "")
        tl_wise[tl_code]["total"] += 1
        if   st == "submitted":    tl_wise[tl_code]["pending"]    += 1
        elif st == "TL_approved":  tl_wise[tl_code]["tlApproved"] += 1
        elif st == "TL_rejected":  tl_wise[tl_code]["tlRejected"] += 1
        elif st == "PnD_approved": tl_wise[tl_code]["approved"]   += 1
        elif st == "PnD_rejected": tl_wise[tl_code]["rejected"]   += 1
        sp = r.get("selfPercentage") or r.get("percentage")
        tl_wise[tl_code]["employees"].append({
            "employeeId":     r["employeeId"],
            "employeeName":   r.get("employeeName", ""),
            "tlName":         tl_name,
            "pndName":        (r.get("partnerEmpName") or "").strip() or "—",
            "status":         st,
            "selfPercentage": sp,
            "tlPercentage":   r.get("tlPercentage"),
            "pndPercentage":  r.get("pndPercentage"),
        })

    # 8. PnD-wise breakdown — now includes employee list for modal filtering
    pnd_wise: dict = {}
    for r in all_records:
        pk = (r.get("partnerEmpCode") or "").strip() or "Unknown"
        pn = (r.get("partnerEmpName") or "").strip() or pk
        if pk not in pnd_wise:
            pnd_wise[pk] = {
                "name": pn, "total": 0, "tlApproved": 0, "pndApproved": 0,
                "employees": []  # ← store employee list for modal filtering
            }
        pnd_wise[pk]["total"] += 1
        st = r.get("status", "")
        if st == "TL_approved":  pnd_wise[pk]["tlApproved"]  += 1
        if st == "PnD_approved": pnd_wise[pk]["pndApproved"] += 1
        sp = r.get("selfPercentage") or r.get("percentage")
        tl_name = (r.get("reportingEmpName") or "").strip() or "—"
        pnd_wise[pk]["employees"].append({
            "employeeId":     r["employeeId"],
            "employeeName":   r.get("employeeName", ""),
            "tlName":         tl_name,
            "pndName":        pn,
            "status":         st,
            "selfPercentage": sp,
            "tlPercentage":   r.get("tlPercentage"),
            "pndPercentage":  r.get("pndPercentage"),
        })

    # 9. Enrich top5ByPartner with avg scores
    for pk, pdata in pnd_top5.items():
        partner_recs = [r for r in all_records if r.get("partnerEmpCode", "").upper() == pk.upper()]
        pdata["avgSelf"] = _avg([r.get("selfPercentage") or r.get("percentage") for r in partner_recs])
        pdata["avgTL"]   = _avg([r.get("tlPercentage")  for r in partner_recs])
        pdata["avgPnd"]  = _avg([r.get("pndPercentage") for r in partner_recs])

    return {
        "success":              True,
        "period":               p,
        "totalApproved":        len(records),
        "top5Overall":          top5_overall,
        "top5ByPartner":        pnd_top5,
        "avgScores":            {"self": avg_self, "tl": avg_tl, "pnd": avg_pnd},
        "designationBreakdown": desig_counts,
        "scoreVariance":        inflation_sorted,
        "pipeline":             pipeline_counts,
        "tlWise":               tl_wise,
        "pndWise":              pnd_wise,
    }

# ─────────────────────────────────────────────────────────────────────────────
# Analysis — KRA detail for employee modal (admin/partner access)
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/analysis/kra/{emp_id}")
async def analysis_kra_detail(emp_id: str, quarter_id: Optional[str] = None, current_user: str = Depends(get_current_user)):
    """
    Returns the full KRA record for an employee including questions and all
    three tiers of answers (self, TL, PnD) for display in the analysis modal.
    Accessible to admin or partner only.
    """
    role     = _resolve_role(current_user)
    is_admin = _is_admin(current_user)
    if role not in ("partner", "admin") and not is_admin:
        raise HTTPException(403, "Admin or Partner access required")

    qid = _resolve_quarter_id(quarter_id)
    if not qid:
        raise HTTPException(404, "No active or selected quarter.")
    record = appraisal_collection.find_one(
        {"employeeId": emp_id.upper(), "quarter_id": qid},
        sort=[("updatedAt", -1)]
    )
    if not record:
        raise HTTPException(404, "No KRA record found for this employee.")

    emp         = employee_details_collection.find_one({"EmpID": emp_id.strip().upper()})
    designation = emp.get("Designation Name", "") if emp else record.get("designation", "")
    questions   = get_questions_for_employee(emp_id, designation)

    result = _serialize(record)

    # Backfill legacy name fields
    if not result.get("partnerEmpName"):
        result["partnerEmpName"] = (result.get("partner", "") or
                                    (emp.get("Partner", "") if emp else ""))
    if not result.get("reportingEmpName"):
        result["reportingEmpName"] = (result.get("reportingManager", "") or
                                      (emp.get("ReportingEmpName", "") if emp else ""))
    if not result.get("selfPercentage"):
        result["selfPercentage"] = result.get("percentage") or result.get("score")

    result["questions"] = questions
    return {"success": True, "data": result}


# ─────────────────────────────────────────────────────────────────────────────
# Manager review — backwards compat
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/review/{emp_id}")
async def review_appraisal(emp_id: str, current_user: str = Depends(get_current_user)):
    live = _get_live_cycle()
    record = None
    if live:
        record = appraisal_collection.find_one(
            {"employeeId": emp_id.upper(), "quarter_id": live["quarter_id"]},
            sort=[("updatedAt", -1)]
        )
    if not record:
        raise HTTPException(404, "No appraisal found for this employee.")
    result = _serialize(record)
    return {"success": True, **result}