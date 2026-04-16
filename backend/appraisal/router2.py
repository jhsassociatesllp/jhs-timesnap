# backend/appraisal/router.py
"""
All /appraisal/* API routes — with full 3-tier approval system.

Role resolution (checked on every request via /appraisal/my_role):
  admin   → present in admin_details_collection (Appraisal DB)
  partner → Grade Name == "PnD" in employee_details (Timesheets DB)
  tl      → present as ReportingEmpCode in reporting_managers (Timesheets DB)
  employee→ everyone else

A partner who is also a TL is treated purely as a partner.

Status flow:
  submitted → TL_approved / TL_rejected → PnD_approved / PnD_rejected
"""

from datetime import date, datetime
from typing import Optional

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException

from backend.auth import get_current_user
from backend.database import (
    employee_details_collection,   # Timesheets DB
    appraisal_collection,          # Appraisal DB  (Appraisal_data)
    admin_details_collection,      # Appraisal DB  (admin_details)
)
from backend.appraisal.models import AppraisalSaveRequest, AppraisalReviewRequest
from backend.appraisal.questions import (
    get_questions_for_employee,
    calculate_score,
)

# We need the Timesheets DB directly for reporting_managers collection
from backend.database import db as timesheets_db   # assumed export; see note below

reporting_managers_collection = timesheets_db["Reporting_managers"]

router = APIRouter(prefix="/appraisal", tags=["Appraisal"])


# ─────────────────────────────────────────────────────────────────────────────
# Role helpers
# ─────────────────────────────────────────────────────────────────────────────

def _is_admin(emp_id: str) -> bool:
    doc = admin_details_collection.find_one({})
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
    """Return: 'admin' | 'partner' | 'tl' | 'employee'"""
    uid = emp_id.strip().upper()
    if _is_admin(uid):
        # Admin + PnD → PnD flow; Admin + TL → TL flow; pure admin → admin
        if _is_partner(uid):
            return "partner"
        if _is_tl(uid):
            return "tl"
        return "admin"
    if _is_partner(uid):
        return "partner"
    if _is_tl(uid):
        return "tl"
    return "employee"


def _get_tl_for_employee(emp_id: str) -> Optional[str]:
    """Return the ReportingEmpCode for a given employee."""
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
    """All employees whose ReportingEmpCode == tl_id."""
    return list(employee_details_collection.find(
        {"ReportingEmpCode": tl_id.strip().upper()},
        {"EmpID": 1, "Emp Name": 1, "Designation Name": 1}
    ))


def _employees_under_partner(partner_id: str) -> list[dict]:
    """All employees whose PartnerEmpCode == partner_id."""
    return list(employee_details_collection.find(
        {"PartnerEmpCode": partner_id.strip().upper()},
        {"EmpID": 1, "Emp Name": 1, "Designation Name": 1, "ReportingEmpCode": 1}
    ))


def _tls_under_partner(partner_id: str) -> list[str]:
    """Unique TL emp codes that are ReportingEmpCodes for employees under this partner."""
    emps = _employees_under_partner(partner_id)
    tl_codes = set()
    for e in emps:
        rc = e.get("ReportingEmpCode", "")
        if rc:
            tl_codes.add(rc.upper())
    return list(tl_codes)


# ─────────────────────────────────────────────────────────────────────────────
# Period helper
# ─────────────────────────────────────────────────────────────────────────────

def _get_current_period() -> str:
    today = date.today()
    if today.month >= 4:
        return f"{today.year}-{str(today.year + 1)[2:]}"
    return f"{today.year - 1}-{str(today.year)[2:]}"


def _check_eligibility(emp_id: str) -> dict:
    emp = employee_details_collection.find_one({"EmpID": emp_id.strip().upper()})
    if not emp:
        return {"eligible": False, "reason": "Employee record not found.", "doj": None, "one_year_date": None}
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
    """
    Convert ObjectId to str and normalize legacy field names.
    Old documents stored score/maxScore/percentage at top level (self score).
    New documents use selfScore/selfMaxScore/selfPercentage.
    We always expose the self-* names so the UI never sees nulls.
    """
    doc["id"] = str(doc.pop("_id", ""))

    # Back-compat: old docs have score/maxScore/percentage as self scores
    if doc.get("selfScore")      is None and doc.get("score")      is not None:
        doc["selfScore"]      = doc["score"]
    if doc.get("selfMaxScore")   is None and doc.get("maxScore")   is not None:
        doc["selfMaxScore"]   = doc["maxScore"]
    if doc.get("selfPercentage") is None and doc.get("percentage") is not None:
        doc["selfPercentage"] = doc["percentage"]

    return doc


# ─────────────────────────────────────────────────────────────────────────────
# Routes — meta
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/period")
async def get_period(current_user: str = Depends(get_current_user)):
    return {"period": _get_current_period()}


@router.get("/my_role")
async def get_my_role(current_user: str = Depends(get_current_user)):
    """Return the resolved role for the logged-in user."""
    role = _resolve_role(current_user)
    emp  = employee_details_collection.find_one(
        {"EmpID": current_user.upper()},
        {"Emp Name": 1, "Designation Name": 1, "Grade Name": 1}
    )
    return {
        "role":        role,
        "empId":       current_user.upper(),
        "name":        emp.get("Emp Name", "") if emp else "",
        "designation": emp.get("Designation Name", "") if emp else "",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Routes — employee
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
    partner_name= emp.get("PartnerEmpName") or "" if emp else ""
    reporting   = emp.get("ReportingEmpCode") or "" if emp else ""
    reporting_name = emp.get("ReportingEmpName") or "" if emp else ""

    period   = data.period or _get_current_period()
    now_iso  = datetime.utcnow().isoformat()

    existing_submitted = appraisal_collection.find_one({
        "employeeId": data.employeeId.upper(),
        "period":     period,
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
        "period":            period,
        "answers":           data.answers,
        "status":            data.status,
        # Self-score — stored under both names for backwards compatibility
        "score":             scoring["score"],
        "maxScore":          scoring["max_score"],
        "percentage":        scoring["percentage"],
        "selfScore":         scoring["score"],
        "selfMaxScore":      scoring["max_score"],
        "selfPercentage":    scoring["percentage"],
        # Will be filled later
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
        "period":     period,
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
        {"_id": 1, "period": 1, "status": 1, "updatedAt": 1,
         "createdAt": 1, "answers": 1, "designation": 1}
    ))
    result = []
    for r in records:
        result.append({
            "id":          str(r["_id"]),
            "period":      r.get("period"),
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
    period = _get_current_period()
    record = appraisal_collection.find_one(
        {"employeeId": emp_id.upper(), "period": period},
        sort=[("updatedAt", -1)]
    )
    if not record:
        return {"success": True, "status": "not_started", "period": period, "id": None, "answers": {}}
    return {
        "success":   True,
        "status":    record.get("status"),
        "period":    period,
        "id":        str(record["_id"]),
        "updatedAt": record.get("updatedAt"),
        "answers":   record.get("answers", {}),
    }


@router.get("/my_status_detail/{emp_id}")
async def get_my_status_detail(emp_id: str, current_user: str = Depends(get_current_user)):
    """
    Returns rich approval-pipeline status for the status tab.
    Works for employees, TLs, and admins.
    For employees: shows self → TL → PnD pipeline.
    For TLs: shows self KRA pipeline (TL is also an employee).
    """
    if emp_id.upper() != current_user.upper():
        raise HTTPException(403, "Unauthorized")

    period = _get_current_period()
    record = appraisal_collection.find_one(
        {"employeeId": emp_id.upper(), "period": period},
        sort=[("updatedAt", -1)]
    )

    emp = employee_details_collection.find_one({"EmpID": emp_id.strip().upper()})
    tl_code      = emp.get("ReportingEmpCode", "") if emp else ""
    tl_name      = emp.get("ReportingEmpName", "") if emp else ""
    partner_code = emp.get("PartnerEmpCode",   "") if emp else ""
    partner_name = emp.get("PartnerEmpName",   "") if emp else ""

    # Determine levels — if TL and partner are same person, only 2 levels
    tl_is_partner = tl_code and partner_code and tl_code.upper() == partner_code.upper()

    if not record:
        return {
            "success":      True,
            "period":       period,
            "status":       "not_started",
            "tlIsSameAsPartner": tl_is_partner,
            "levels":       _build_pipeline(None, tl_name, partner_name, tl_is_partner),
        }

    status = record.get("status", "not_started")
    return {
        "success":           True,
        "period":            period,
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
    """Build a list of pipeline steps with done/active/pending state."""
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
        {"label": "Self Submission",  "actor": "You",          "state": _step_state("submitted")},
        {"label": f"TL Approval",     "actor": tl_name or "TL","state": _step_state("TL_approved", "TL_rejected")},
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

def _require_tl_or_above(current_user: str):
    role = _resolve_role(current_user)
    if role not in ("tl", "partner", "admin"):
        raise HTTPException(403, "TL or Partner access required")
    return role


@router.get("/tl/pending")
async def tl_pending(current_user: str = Depends(get_current_user)):
    _require_tl_or_above(current_user)
    period = _get_current_period()
    # Find all employees under this TL
    emps = _employees_under_tl(current_user)
    emp_ids = [e["EmpID"].upper() for e in emps]
    # Get submitted (not yet actioned by TL) appraisals
    records = list(appraisal_collection.find({
        "employeeId": {"$in": emp_ids},
        "period":     period,
        "status":     "submitted",
    }, {"_id": 1, "employeeId": 1, "employeeName": 1, "designation": 1,
        "status": 1, "updatedAt": 1, "selfPercentage": 1, "percentage": 1, "score": 1, "maxScore": 1}))
    return {"success": True, "data": [_serialize(r) for r in records]}


@router.get("/tl/approved")
async def tl_approved(current_user: str = Depends(get_current_user)):
    _require_tl_or_above(current_user)
    period = _get_current_period()
    emps   = _employees_under_tl(current_user)
    emp_ids = [e["EmpID"].upper() for e in emps]
    records = list(appraisal_collection.find({
        "employeeId": {"$in": emp_ids},
        "period":     period,
        "status":     "TL_approved",
    }, {"_id": 1, "employeeId": 1, "employeeName": 1, "designation": 1,
        "status": 1, "updatedAt": 1, "selfPercentage": 1, "tlPercentage": 1,
        "tl_responses": 1, "answers": 1, "percentage": 1, "score": 1, "maxScore": 1}))
    return {"success": True, "data": [_serialize(r) for r in records]}


@router.get("/tl/rejected")
async def tl_rejected(current_user: str = Depends(get_current_user)):
    _require_tl_or_above(current_user)
    period = _get_current_period()
    emps   = _employees_under_tl(current_user)
    emp_ids = [e["EmpID"].upper() for e in emps]
    records = list(appraisal_collection.find({
        "employeeId": {"$in": emp_ids},
        "period":     period,
        "status":     "TL_rejected",
    }, {"_id": 1, "employeeId": 1, "employeeName": 1, "designation": 1,
        "status": 1, "updatedAt": 1, "selfPercentage": 1, "tlPercentage": 1,
        "tl_responses": 1, "answers": 1, "percentage": 1, "score": 1, "maxScore": 1}))
    return {"success": True, "data": [_serialize(r) for r in records]}


@router.get("/tl/record/{record_id}")
async def tl_get_record(record_id: str, current_user: str = Depends(get_current_user)):
    """Full record for modal display — TL verifies the employee is theirs."""
    _require_tl_or_above(current_user)
    try:
        oid = ObjectId(record_id)
    except Exception:
        raise HTTPException(400, "Invalid record id")
    record = appraisal_collection.find_one({"_id": oid})
    if not record:
        raise HTTPException(404, "Record not found")

    # Verify ownership
    role = _resolve_role(current_user)
    if role == "tl":
        emps    = _employees_under_tl(current_user)
        emp_ids = [e["EmpID"].upper() for e in emps]
        if record["employeeId"].upper() not in emp_ids:
            raise HTTPException(403, "Not your employee")

    # Attach questions
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
    """
    TL approves or rejects an employee's appraisal.
    Optionally accepts edited answers in data.tl_responses.
    """
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

    # Verify TL owns this employee
    role = _resolve_role(current_user)
    if role == "tl":
        emps    = _employees_under_tl(current_user)
        emp_ids = [e["EmpID"].upper() for e in emps]
        if record["employeeId"].upper() not in emp_ids:
            raise HTTPException(403, "Not your employee")

    new_status = "TL_approved" if data.action == "approve" else "TL_rejected"
    now_iso    = datetime.utcnow().isoformat()

    update = {
        "status":           new_status,
        "tlActionBy":       current_user.upper(),
        "tlActionAt":       now_iso,
        "updatedAt":        now_iso,
    }

    # If TL provided edited responses, compute TL score
    if data.tl_responses:
        emp         = employee_details_collection.find_one({"EmpID": record["employeeId"].upper()})
        designation = emp.get("Designation Name", "") if emp else ""
        tl_scoring  = calculate_score(record["employeeId"], designation, data.tl_responses)
        update["tl_responses"]  = data.tl_responses
        update["tlScore"]       = tl_scoring["score"]
        update["tlMaxScore"]    = tl_scoring["max_score"]
        update["tlPercentage"]  = tl_scoring["percentage"]
    else:
        # TL used employee answers as-is — copy self score
        # Fall back to legacy field names for old documents
        update["tl_responses"]  = record.get("answers", {})
        update["tlScore"]       = record.get("selfScore")      or record.get("score")
        update["tlMaxScore"]    = record.get("selfMaxScore")   or record.get("maxScore")
        update["tlPercentage"]  = record.get("selfPercentage") or record.get("percentage")

    if data.remarks:
        update["tlRemarks"] = data.remarks

    appraisal_collection.update_one({"_id": oid}, {"$set": update})
    return {"success": True, "message": f"Record {new_status}", "status": new_status}


# ─────────────────────────────────────────────────────────────────────────────
# Routes — Partner / Director (PnD)
# ─────────────────────────────────────────────────────────────────────────────

def _require_partner_or_admin(current_user: str):
    role = _resolve_role(current_user)
    if role not in ("partner", "admin"):
        raise HTTPException(403, "Partner access required")
    return role


def _pnd_pending_employees(partner_id: str, period: str):
    """Employees under partner whose status is TL_approved."""
    emps    = _employees_under_partner(partner_id)
    emp_ids = [e["EmpID"].upper() for e in emps]
    tl_codes = set(e.get("ReportingEmpCode", "").upper() for e in emps if e.get("ReportingEmpCode"))
    # Exclude TLs from employee list
    emp_ids_excl_tls = [eid for eid in emp_ids if eid not in tl_codes]
    records = list(appraisal_collection.find({
        "employeeId": {"$in": emp_ids_excl_tls},
        "period":     period,
        "status":     "TL_approved",
    }, {"_id": 1, "employeeId": 1, "employeeName": 1, "designation": 1,
        "status": 1, "updatedAt": 1, "selfPercentage": 1, "tlPercentage": 1, "percentage": 1, "score": 1, "maxScore": 1}))
    return [_serialize(r) for r in records]


def _pnd_pending_tls(partner_id: str, period: str):
    """TLs under partner whose KRA status is submitted (TLs go direct to PnD)."""
    tl_codes = _tls_under_partner(partner_id)
    records = list(appraisal_collection.find({
        "employeeId": {"$in": tl_codes},
        "period":     period,
        "status":     "submitted",
    }, {"_id": 1, "employeeId": 1, "employeeName": 1, "designation": 1,
        "status": 1, "updatedAt": 1, "selfPercentage": 1, "percentage": 1, "score": 1, "maxScore": 1}))
    return [_serialize(r) for r in records]


@router.get("/pnd/pending")
async def pnd_pending(current_user: str = Depends(get_current_user)):
    _require_partner_or_admin(current_user)
    period = _get_current_period()
    return {
        "success":   True,
        "employees": _pnd_pending_employees(current_user, period),
        "tls":       _pnd_pending_tls(current_user, period),
    }


@router.get("/pnd/approved")
async def pnd_approved(current_user: str = Depends(get_current_user)):
    _require_partner_or_admin(current_user)
    period  = _get_current_period()
    emps    = _employees_under_partner(current_user)
    all_ids = [e["EmpID"].upper() for e in emps]
    tl_ids  = set(_tls_under_partner(current_user))
    emp_ids = [eid for eid in all_ids if eid not in tl_ids]

    emp_records = list(appraisal_collection.find({
        "employeeId": {"$in": emp_ids},
        "period":     period,
        "status":     "PnD_approved",
    }, {"_id": 1, "employeeId": 1, "employeeName": 1, "designation": 1,
        "status": 1, "updatedAt": 1, "selfPercentage": 1,
        "tlPercentage": 1, "pndPercentage": 1,
        "tl_responses": 1, "pnd_responses": 1, "answers": 1, "percentage": 1, "score": 1, "maxScore": 1}))

    tl_records = list(appraisal_collection.find({
        "employeeId": {"$in": list(tl_ids)},
        "period":     period,
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
async def pnd_rejected(current_user: str = Depends(get_current_user)):
    _require_partner_or_admin(current_user)
    period  = _get_current_period()
    emps    = _employees_under_partner(current_user)
    all_ids = [e["EmpID"].upper() for e in emps]
    tl_ids  = set(_tls_under_partner(current_user))
    emp_ids = [eid for eid in all_ids if eid not in tl_ids]

    emp_records = list(appraisal_collection.find({
        "employeeId": {"$in": emp_ids},
        "period":     period,
        "status":     "PnD_rejected",
    }, {"_id": 1, "employeeId": 1, "employeeName": 1, "designation": 1,
        "status": 1, "updatedAt": 1, "selfPercentage": 1,
        "tlPercentage": 1, "pndPercentage": 1,
        "tl_responses": 1, "pnd_responses": 1, "answers": 1, "percentage": 1, "score": 1, "maxScore": 1}))

    tl_records = list(appraisal_collection.find({
        "employeeId": {"$in": list(tl_ids)},
        "period":     period,
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
    _require_partner_or_admin(current_user)
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
    _require_partner_or_admin(current_user)
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

    new_status = "PnD_approved" if data.action == "approve" else "PnD_rejected"
    now_iso    = datetime.utcnow().isoformat()

    update = {
        "status":       new_status,
        "pndActionBy":  current_user.upper(),
        "pndActionAt":  now_iso,
        "updatedAt":    now_iso,
    }

    if data.pnd_responses:
        emp         = employee_details_collection.find_one({"EmpID": record["employeeId"].upper()})
        designation = emp.get("Designation Name", "") if emp else ""
        pnd_scoring = calculate_score(record["employeeId"], designation, data.pnd_responses)
        update["pnd_responses"]  = data.pnd_responses
        update["pndScore"]       = pnd_scoring["score"]
        update["pndMaxScore"]    = pnd_scoring["max_score"]
        update["pndPercentage"]  = pnd_scoring["percentage"]
    else:
        # Use TL score if available, else self score
        tl_resp = record.get("tl_responses") or record.get("answers", {})
        update["pnd_responses"]  = tl_resp
        update["pndScore"]       = record.get("tlScore")       or record.get("selfScore")      or record.get("score")
        update["pndMaxScore"]    = record.get("tlMaxScore")    or record.get("selfMaxScore")   or record.get("maxScore")
        update["pndPercentage"]  = record.get("tlPercentage")  or record.get("selfPercentage") or record.get("percentage")

    if data.remarks:
        update["pndRemarks"] = data.remarks

    appraisal_collection.update_one({"_id": oid}, {"$set": update})
    return {"success": True, "message": f"Record {new_status}", "status": new_status}


# ─────────────────────────────────────────────────────────────────────────────
# Routes — Admin
# ─────────────────────────────────────────────────────────────────────────────

def _require_admin(current_user: str):
    if not _is_admin(current_user):
        raise HTTPException(403, "Admin access required")


@router.get("/admin/pending")
async def admin_pending(current_user: str = Depends(get_current_user)):
    """Admin sees all submitted/TL_approved records across all periods."""
    _require_admin(current_user)
    records = list(appraisal_collection.find(
        {"status": {"$in": ["submitted", "TL_approved"]}},
        {"_id": 1, "employeeId": 1, "employeeName": 1, "designation": 1,
         "status": 1, "updatedAt": 1, "selfPercentage": 1, "tlPercentage": 1,
         "reportingEmpCode": 1, "partnerEmpCode": 1, "percentage": 1, "score": 1, "maxScore": 1}
    ))
    return {"success": True, "data": [_serialize(r) for r in records]}


@router.get("/admin/approved")
async def admin_approved(current_user: str = Depends(get_current_user)):
    _require_admin(current_user)
    records = list(appraisal_collection.find(
        {"status": "PnD_approved"},
        {"_id": 1, "employeeId": 1, "employeeName": 1, "designation": 1,
         "status": 1, "updatedAt": 1, "selfPercentage": 1,
         "tlPercentage": 1, "pndPercentage": 1,
         "reportingEmpCode": 1, "partnerEmpCode": 1, "partnerEmpName": 1, "percentage": 1, "score": 1, "maxScore": 1}
    ))
    return {"success": True, "data": [_serialize(r) for r in records]}


@router.get("/admin/rejected")
async def admin_rejected(current_user: str = Depends(get_current_user)):
    _require_admin(current_user)
    records = list(appraisal_collection.find(
        {"status": {"$in": ["TL_rejected", "PnD_rejected"]}},
        {"_id": 1, "employeeId": 1, "employeeName": 1, "designation": 1,
         "status": 1, "updatedAt": 1, "selfPercentage": 1, "tlPercentage": 1,
         "reportingEmpCode": 1, "partnerEmpCode": 1, "percentage": 1, "score": 1, "maxScore": 1}
    ))
    return {"success": True, "data": [_serialize(r) for r in records]}


# ─────────────────────────────────────────────────────────────────────────────
# Routes — Analysis (admin + partner)
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/analysis")
async def get_analysis(
    current_user: str = Depends(get_current_user),
    period: Optional[str] = None,
):
    role = _resolve_role(current_user)
    if role not in ("admin", "partner"):
        raise HTTPException(403, "Admin or Partner access required")

    # Admin: if no period specified, query ALL periods (no period filter)
    # Partner: same — all periods unless specified
    # Either role can pass ?period=2025-26 to filter to a specific year
    query_approved: dict = {"status": "PnD_approved"}
    query_all: dict = {}

    if period:
        query_approved["period"] = period
        query_all["period"]      = period

    if role == "partner":
        query_approved["partnerEmpCode"] = current_user.upper()
        query_all["partnerEmpCode"]      = current_user.upper()

    records = list(appraisal_collection.find(query_approved, {
        "_id": 1, "employeeId": 1, "employeeName": 1, "designation": 1,
        "partnerEmpCode": 1, "partnerEmpName": 1,
        "selfPercentage": 1, "tlPercentage": 1, "pndPercentage": 1,
        "selfScore": 1, "tlScore": 1, "pndScore": 1,
        "selfMaxScore": 1, "percentage": 1, "score": 1, "maxScore": 1,
    }))

    # Build analysis payload
    # 1. Overall top 5
    sorted_all = sorted(records, key=lambda r: r.get("pndPercentage") or 0, reverse=True)
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
        pk = r.get("partnerEmpCode", "Unknown")
        pn = r.get("partnerEmpName", pk)
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
                    "selfPct":      r.get("selfPercentage") or r.get("percentage"),
                    "tlPct":        r.get("tlPercentage"),
                    "pndPct":       r.get("pndPercentage"),
                }
                for r in sorted_g[:5]
            ]
        }

    # 3. Score progression stats (avg self vs tl vs pnd)
    def _avg(lst):
        lst = [x for x in lst if x is not None]
        return round(sum(lst) / len(lst), 2) if lst else None

    avg_self = _avg([r.get("selfPercentage") for r in records])
    avg_tl   = _avg([r.get("tlPercentage") for r in records])
    avg_pnd  = _avg([r.get("pndPercentage") for r in records])

    # 4. Designation distribution
    desig_counts: dict[str, int] = {}
    for r in records:
        d = r.get("designation", "Unknown")
        desig_counts[d] = desig_counts.get(d, 0) + 1

    # 5. Score inflation/deflation (self vs final)
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

    # 6. Pipeline counts — ALL records (not just approved)
    all_records = list(appraisal_collection.find(query_all, {
        "_id": 1, "employeeId": 1, "employeeName": 1, "designation": 1,
        "status": 1, "reportingEmpCode": 1, "reportingEmpName": 1,
        "partnerEmpCode": 1, "partnerEmpName": 1,
        "selfPercentage": 1, "tlPercentage": 1, "pndPercentage": 1,
        "percentage": 1, "score": 1,
    }))

    pipeline_counts = {
        "pending":    sum(1 for r in all_records if r.get("status") == "submitted"),
        "tlApproved": sum(1 for r in all_records if r.get("status") == "TL_approved"),
        "tlRejected": sum(1 for r in all_records if r.get("status") == "TL_rejected"),
        "pndApproved":sum(1 for r in all_records if r.get("status") == "PnD_approved"),
        "pndRejected":sum(1 for r in all_records if r.get("status") == "PnD_rejected"),
    }

    # 7. TL-wise breakdown
    tl_wise: dict = {}
    for r in all_records:
        tl_code = r.get("reportingEmpCode", "Unknown") or "Unknown"
        tl_name = r.get("reportingEmpName", tl_code) or tl_code
        if tl_code not in tl_wise:
            tl_wise[tl_code] = {
                "name": tl_name, "total": 0,
                "pending": 0, "tlApproved": 0, "tlRejected": 0,
                "approved": 0, "rejected": 0, "employees": []
            }
        st = r.get("status", "")
        tl_wise[tl_code]["total"] += 1
        if st == "submitted":           tl_wise[tl_code]["pending"]    += 1
        elif st == "TL_approved":       tl_wise[tl_code]["tlApproved"] += 1
        elif st == "TL_rejected":       tl_wise[tl_code]["tlRejected"] += 1
        elif st == "PnD_approved":      tl_wise[tl_code]["approved"]   += 1
        elif st == "PnD_rejected":      tl_wise[tl_code]["rejected"]   += 1
        sp = r.get("selfPercentage") or r.get("percentage")
        tl_wise[tl_code]["employees"].append({
            "employeeId":     r["employeeId"],
            "employeeName":   r.get("employeeName", ""),
            "status":         st,
            "selfPercentage": sp,
            "tlPercentage":   r.get("tlPercentage"),
            "pndPercentage":  r.get("pndPercentage"),
        })

    # 8. PnD-wise pending breakdown
    pnd_wise: dict = {}
    for r in all_records:
        pk   = r.get("partnerEmpCode", "Unknown") or "Unknown"
        pn   = r.get("partnerEmpName", pk) or pk
        if pk not in pnd_wise:
            pnd_wise[pk] = {"name": pn, "total": 0, "tlApproved": 0, "pndApproved": 0}
        pnd_wise[pk]["total"] += 1
        if r.get("status") == "TL_approved":  pnd_wise[pk]["tlApproved"]  += 1
        if r.get("status") == "PnD_approved": pnd_wise[pk]["pndApproved"] += 1

    # 9. Enrich top5ByPartner with avg scores
    for pk, pdata in pnd_top5.items():
        partner_recs = [r for r in all_records if r.get("partnerEmpCode","").upper() == pk.upper()]
        pdata["avgSelf"] = _avg([r.get("selfPercentage") or r.get("percentage") for r in partner_recs])
        pdata["avgTL"]   = _avg([r.get("tlPercentage")  for r in partner_recs])
        pdata["avgPnd"]  = _avg([r.get("pndPercentage") for r in partner_recs])

    return {
        "success":              True,
        "period":               period,
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
# Manager review (existing — keep for backwards compat)
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/review/{emp_id}")
async def review_appraisal(emp_id: str, current_user: str = Depends(get_current_user)):
    period = _get_current_period()
    record = appraisal_collection.find_one(
        {"employeeId": emp_id.upper(), "period": period},
        sort=[("updatedAt", -1)]
    )
    if not record:
        raise HTTPException(404, "No appraisal found for this employee.")
    result = _serialize(record)
    return {"success": True, **result}