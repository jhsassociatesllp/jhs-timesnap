# backend/appraisal/router.py
"""
All /appraisal/* API routes.

Endpoints:
  GET  /appraisal/eligibility/{emp_id}          → check if eligible
  GET  /appraisal/questions/{emp_id}            → get questions (no weightage)
  POST /appraisal/save                          → save draft or submit
  GET  /appraisal/my/{emp_id}                   → employee's own history
  GET  /appraisal/status/{emp_id}               → latest submission status
  GET  /appraisal/review/{emp_id}               → manager/partner view (full data + score)
  GET  /appraisal/period                        → current active appraisal period
"""

from datetime import date, datetime, timedelta
from typing import Optional

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException

from backend.auth import get_current_user
from backend.database import employee_details_collection, appraisal_collection, admin_details_collection
from backend.appraisal.models import AppraisalSaveRequest
from backend.appraisal.questions import (
    get_questions_for_employee,
    calculate_score,
)

router = APIRouter(prefix="/appraisal", tags=["Appraisal"])


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

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


def _get_current_period() -> str:
    """Return appraisal period string like '2024-25'."""
    today = date.today()
    # Appraisal year: April to March
    if today.month >= 4:
        return f"{today.year}-{str(today.year + 1)[2:]}"
    return f"{today.year - 1}-{str(today.year)[2:]}"


def _check_eligibility(emp_id: str) -> dict:
    emp = employee_details_collection.find_one({"EmpID": emp_id.strip().upper()})
    if not emp:
        return {"eligible": False, "reason": "Employee record not found.", "doj": None, "one_year_date": None}

    # doj = _parse_doj(emp.get("Date of Joining") or emp.get("DateOfJoining"))
    # if not doj:
    #     return {"eligible": False, "reason": "Date of Joining not found in your record.", "doj": None, "one_year_date": None}

    # try:
    #     one_year = date(doj.year + 1, doj.month, doj.day)
    # except ValueError:
    #     # handle Feb 29
    #     one_year = date(doj.year + 1, doj.month, 28)

    # today = date.today()

    # # Eligible if: completed 1 year already  OR  completing in March of current year
    # current_year = today.year
    # march_start  = date(current_year, 3, 1)
    # march_end    = date(current_year, 3, 31)

    # completed    = one_year <= today
    # in_march     = march_start <= one_year <= march_end

    # if completed or in_march:
    #     return {
    #         "eligible":      True,
    #         "reason":        "You have completed 1 year of service." if completed
    #                          else f"You are completing 1 year of service in March {current_year}.",
    #         "doj":           doj.strftime("%d/%m/%Y"),
    #         "one_year_date": one_year.strftime("%d/%m/%Y"),
    #     }

    # return {
    #     "eligible":      False,
    #     "reason":        f"You will complete 1 year of service on {one_year.strftime('%d/%m/%Y')}. "
    #                      "Appraisal is available after 1 year of service or if your anniversary falls in March.",
    #     "doj":           doj.strftime("%d/%m/%Y"),
    #     "one_year_date": one_year.strftime("%d/%m/%Y"),
    # }
    
    return {
        "eligible":      True,
        "reason":        "",
        "doj":           "",
        "one_year_date": "",
    }
    


# ─────────────────────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/eligibility/{emp_id}")
async def check_eligibility(emp_id: str, current_user: str = Depends(get_current_user)):
    if emp_id.upper() != current_user.upper():
        raise HTTPException(status_code=403, detail="Unauthorized")
    return _check_eligibility(emp_id)


@router.get("/questions/{emp_id}")
async def get_questions(emp_id: str, current_user: str = Depends(get_current_user)):
    if emp_id.upper() != current_user.upper():
        raise HTTPException(status_code=403, detail="Unauthorized")

    elig = _check_eligibility(emp_id)
    if not elig["eligible"]:
        raise HTTPException(status_code=403, detail=elig["reason"])

    emp = employee_details_collection.find_one({"EmpID": emp_id.strip().upper()})
    designation = emp.get("Designation Name", "") if emp else ""
    return get_questions_for_employee(emp_id, designation)


@router.post("/save")
async def save_appraisal(data: AppraisalSaveRequest, current_user: str = Depends(get_current_user)):
    if data.employeeId.upper() != current_user.upper():
        raise HTTPException(status_code=403, detail="Unauthorized")

    elig = _check_eligibility(data.employeeId)
    if not elig["eligible"]:
        raise HTTPException(status_code=403, detail=elig["reason"])

    if data.status not in ("draft", "submitted"):
        raise HTTPException(status_code=400, detail="status must be 'draft' or 'submitted'")

    emp = employee_details_collection.find_one({"EmpID": data.employeeId.strip().upper()})
    emp_id = emp.get("EmpID", "") if emp else ""
    designation = emp.get("Designation Name", "") if emp else ""
    emp_name    = emp.get("Name") or emp.get("Emp Name") or "" if emp else ""
    partner     = emp.get("Partner") or "" if emp else ""
    reporting   = emp.get("ReportingEmpName") or "" if emp else ""

    period   = data.period or _get_current_period()
    now_iso  = datetime.utcnow().isoformat()

    # Check if a SUBMITTED record already exists for this period
    existing_submitted = appraisal_collection.find_one({
        "employeeId": data.employeeId.upper(),
        "period":     period,
        "status":     "submitted",
    })
    if existing_submitted:
        raise HTTPException(
            status_code=400,
            detail="Appraisal already submitted for this period. Submitted appraisals cannot be edited."
        )

    # Calculate score (backend only, not returned to employee)
    scoring = calculate_score(emp_id, designation, data.answers)

    doc = {
        "employeeId":        data.employeeId.upper(),
        "employeeName":      emp_name,
        "designation":       designation,
        "partner":           partner,
        "reportingManager":  reporting,
        "period":            period,
        "answers":           data.answers,
        "status":            data.status,
        "score":             scoring["score"],
        "maxScore":          scoring["max_score"],
        "percentage":        scoring["percentage"],
        "questionSource":    scoring.get("source", "none"),   # "emp_code" | "level_1" | "level_2" | "cybersecurity" | "none"
        "updatedAt":         now_iso,
    }

    # Upsert on (employeeId, period) — only for drafts
    existing_draft = appraisal_collection.find_one({
        "employeeId": data.employeeId.upper(),
        "period":     period,
        "status":     "draft",
    })

    if existing_draft:
        appraisal_collection.update_one(
            {"_id": existing_draft["_id"]},
            {"$set": doc}
        )
        record_id = str(existing_draft["_id"])
    else:
        doc["createdAt"] = now_iso
        result    = appraisal_collection.insert_one(doc)
        record_id = str(result.inserted_id)

    return {
        "success": True,
        "message": "KRA submitted successfully!" if data.status == "submitted"
                   else "Draft saved successfully.",
        "id":      record_id,
        "status":  data.status,
    }


@router.get("/my/{emp_id}")
async def get_my_appraisals(emp_id: str, current_user: str = Depends(get_current_user)):
    if emp_id.upper() != current_user.upper():
        raise HTTPException(status_code=403, detail="Unauthorized")

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
        raise HTTPException(status_code=403, detail="Unauthorized")

    period = _get_current_period()

    # Check submitted first
    submitted = appraisal_collection.find_one(
        {"employeeId": emp_id.upper(), "period": period, "status": "submitted"},
        {"_id": 1, "status": 1, "updatedAt": 1, "answers": 1}
    )
    if submitted:
        return {
            "success":   True,
            "status":    "submitted",
            "period":    period,
            "id":        str(submitted["_id"]),
            "updatedAt": submitted.get("updatedAt"),
            "answers":   submitted.get("answers", {}),
        }

    # Check draft
    draft = appraisal_collection.find_one(
        {"employeeId": emp_id.upper(), "period": period, "status": "draft"},
        {"_id": 1, "status": 1, "updatedAt": 1, "answers": 1}
    )
    if draft:
        return {
            "success":   True,
            "status":    "draft",
            "period":    period,
            "id":        str(draft["_id"]),
            "updatedAt": draft.get("updatedAt"),
            "answers":   draft.get("answers", {}),
        }

    return {
        "success": True,
        "status":  "not_started",
        "period":  period,
        "id":      None,
        "answers": {},
    }


@router.get("/period")
async def get_period(current_user: str = Depends(get_current_user)):
    return {"period": _get_current_period()}


@router.get("/review/{emp_id}")
async def review_appraisal(emp_id: str, current_user: str = Depends(get_current_user)):
    """
    For manager / partner / HR use.
    Returns full appraisal data INCLUDING score and percentage.
    Any authenticated user can view — restrict further via role check if needed.
    """
    period  = _get_current_period()
    record  = appraisal_collection.find_one(
        {"employeeId": emp_id.upper(), "period": period},
        sort=[("updatedAt", -1)]
    )
    if not record:
        raise HTTPException(status_code=404, detail="No appraisal found for this employee.")

    return {
        "success":        True,
        "employeeId":     record.get("employeeId"),
        "employeeName":   record.get("employeeName"),
        "designation":    record.get("designation"),
        "partner":        record.get("partner"),
        "reportingManager": record.get("reportingManager"),
        "period":         record.get("period"),
        "status":         record.get("status"),
        "answers":        record.get("answers", {}),
        "score":          record.get("score"),
        "maxScore":       record.get("maxScore"),
        "percentage":     record.get("percentage"),
        "updatedAt":      record.get("updatedAt"),
    }