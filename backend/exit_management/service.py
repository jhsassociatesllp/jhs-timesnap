# backend/exit_management/service.py
"""Business rules: employee details, drafts, validation and atomic submit."""
import logging
from datetime import date

from fastapi import HTTPException
from pymongo.errors import DuplicateKeyError, PyMongoError

from backend.exit_management import repository as repo
from backend.exit_management import approvals, signature
from backend.exit_management.schemas import ExitFormPayload
from backend.exit_management.utils import ALREADY_SUBMITTED, aware, public_form, to_iso_date, utcnow

log = logging.getLogger("exit_management")

# Friendly labels, in paper-form order, used for validation messages.
MANAGER_LABELS = {
    "team_management": "1. Team Management", "communication": "2. Communication",
    "motivation": "3. Motivation", "technical_skills": "4. Technical Skills",
    "fairness": "5. Fairness", "approachability": "6. Approachability",
    "relationship_with_other_teams": "7. Relationship with other teams",
    "management_skills": "8. Management Skills",
}
COMPANY_LABELS = {
    "company_culture": "9. Company Culture", "learning_experience": "10. Learning experience",
    "rewards_recognition": "11. Rewards & Recognition", "performance_review_system": "12. Performance Review System",
    "physical_working_conditions": "13. Physical working conditions", "facilities": "14. Facilities",
    "opportunity_for_growth": "15. Opportunity for growth", "management_skills": "16. Management Skills",
}
# Q22 and the employer name (Q21) are only required when "better prospect" is Yes - handled below.
INTERVIEW_REQUIRED = {
    "would_rejoin": "17. Would you rejoin JHS", "systems_and_processes": "18. Systems and processes",
    "team_experience": "19. Working in your team", "resignation_reason": "20. Reason for resignation",
    "better_prospect": "21. Better prospect (Yes/No)", "recommend_company": "23. Recommend the company",
    "jhs_memories": "24. Three things you would remember", "improvements": "25. Three things that would have made life better",
    "employee_benefits": "26. Employee benefits", "departure_prevention": "27. Circumstances that would have prevented departure",
}


def employee_details(empid: str) -> dict:
    """Section A, built from the Employee_details collection (never from the browser).

    Resignation / last working date are not stored there, so the employee fills them.
    `missing` lists any detail the database does not have, so the page can say so.
    """
    emp = repo.find_employee(empid)
    if not emp:
        raise HTTPException(404, "Your employee record was not found. Please contact HR.")
    details = {
        "employee_name": emp.get("Emp Name") or emp.get("EmployeeName") or emp.get("Name") or "",
        "code": emp.get("EmpID") or empid,
        "designation": emp.get("Designation Name") or emp.get("Designation") or "",
        "joining_date": to_iso_date(emp.get("Date of Joining")),
        "reporting_to": emp.get("ReportingEmpName") or "",
        "reporting_code": emp.get("ReportingEmpCode") or "",     # used to route the first approval
    }
    labels = {"employee_name": "Full name", "designation": "Designation",
              "joining_date": "Joining date", "reporting_to": "Reporting to"}
    details["missing"] = [labels[k] for k in labels if not details[k]]
    details["date"] = date.today().isoformat()
    return details


def _stored_details(emp: dict, p: ExitFormPayload) -> dict:
    return {
        "code": emp["code"], "designation": emp["designation"], "joining_date": emp["joining_date"],
        "reporting_to": emp["reporting_to"],
        "resignation_date": p.resignation_date or "",
        "last_working_date": p.last_working_date or "",
    }


def missing_for_submit(p: ExitFormPayload) -> list:
    """Everything still required before a FINAL submit (empty list = ok)."""
    errors = []
    if not p.resignation_date:
        errors.append("Resignation Date is required")
    if not p.last_working_date:
        errors.append("Last Working Date is required")
    if p.resignation_date and p.last_working_date and p.last_working_date < p.resignation_date:
        errors.append("Last Working Date cannot be before the Resignation Date")
    for key, label in MANAGER_LABELS.items():
        if getattr(p.manager_feedback, key) is None:
            errors.append(f"About Reporting Manager - rate '{label}'")
    for key, label in COMPANY_LABELS.items():
        if getattr(p.company_feedback, key) is None:
            errors.append(f"About JHS - rate '{label}'")
    ei = p.exit_interview
    for key, label in INTERVIEW_REQUIRED.items():
        if not getattr(ei, key):
            errors.append(f"Question '{label}' is required")
    if ei.recommend_company == "No" and not ei.recommend_reason:
        errors.append("Please tell us why you would not recommend the company (Q23)")
    if ei.better_prospect == "Yes":
        if not ei.new_employer:
            errors.append("Please mention the name of your new employer (Q21)")
        if not ei.pull_factors:
            errors.append("Question '22. Pull factors of your new employer' is required")
    return errors


def _fields(emp: dict, p: ExitFormPayload) -> dict:
    ei = p.exit_interview.model_dump()
    if ei.get("better_prospect") != "Yes":      # keep the record consistent with the conditional question
        ei["new_employer"] = ""
    if ei.get("recommend_company") != "No":     # the reason only belongs to a "No" answer
        ei["recommend_reason"] = ""
    return {
        "employee_name": emp["employee_name"],
        "employee_details": _stored_details(emp, p),
        "manager_feedback": p.manager_feedback.model_dump(),
        "company_feedback": p.company_feedback.model_dump(),
        "exit_interview": ei,
    }


def _already_submitted() -> HTTPException:
    return HTTPException(409, ALREADY_SUBMITTED)


def get_draft(empid: str) -> dict:
    doc = repo.find_form(empid)
    if not doc:
        return {"status": "none", "form": None}
    return {"status": doc.get("status", "draft"), "form": public_form(doc)}


def save_draft(empid: str, p: ExitFormPayload) -> dict:
    """Create or update the draft. The filter includes status='draft', so if a
    SUBMITTED form exists the upsert collides with the unique employee_id index
    and is refused (409): a submitted form can never be overwritten."""
    repo.ensure_indexes()
    emp = employee_details(empid)
    now = utcnow()
    try:
        doc = repo.collection.find_one_and_update(
            {"employee_id": empid, "status": "draft"},
            {"$set": {**_fields(emp, p), "updated_at": now},
             "$setOnInsert": {"employee_id": empid, "status": "draft", "created_at": now}},
            upsert=True, return_document=True,
        )
    except DuplicateKeyError:
        raise _already_submitted()
    except PyMongoError:
        log.exception("save_draft failed for %s", empid)
        raise HTTPException(503, "Could not reach the database. Please try again.")
    log.info("exit draft saved for %s", empid)
    return {"status": "draft", "id": str(doc["_id"]), "updated_at": now.isoformat()}


def delete_draft(empid: str) -> dict:
    """Delete the employee's DRAFT (never a submitted form) together with its signature file in GridFS."""
    repo.ensure_indexes()
    try:
        deleted = repo.collection.find_one_and_delete({"employee_id": empid, "status": "draft"})
    except PyMongoError:
        log.exception("delete_draft failed for %s", empid)
        raise HTTPException(503, "Could not reach the database. Please try again.")
    if deleted is None:
        raise HTTPException(404, "No draft to delete.")
    ref = deleted.get("signature_file")
    if ref:
        signature.delete_file(ref.get("gridfs_file_id"))     # no orphaned GridFS file
    return {"deleted": True}


def submit(empid: str, p: ExitFormPayload) -> dict:
    errors = missing_for_submit(p)
    sig_errors, doc = signature.check_for_submit(empid)      # signature file exists in GridFS, is this employee's, valid size
    errors += sig_errors
    if errors:
        raise HTTPException(422, {"message": "Please complete the form before submitting.", "errors": errors})
    repo.ensure_indexes()
    emp = employee_details(empid)
    now = utcnow()
    file_id = doc["signature_file"]["gridfs_file_id"]
    try:
        # One atomic operation: only THIS employee's DRAFT that still points at the verified signature file can
        # become submitted. The signature reference is left exactly as it is (the file is kept permanently).
        saved = repo.collection.find_one_and_update(
            {"employee_id": empid, "status": "draft", "signature_file.gridfs_file_id": file_id},
            {"$set": {**_fields(emp, p), "status": "submitted", "submitted_at": now, "updated_at": now,
                      "approval": approvals.initial_approval(emp["reporting_code"], emp["reporting_to"], now)}},
            return_document=True,
        )
    except PyMongoError:
        log.exception("submit failed for %s", empid)
        raise HTTPException(503, "Could not reach the database. Please try again.")
    if saved is None:
        current = repo.find_form(empid)
        if current and current.get("status") == "submitted":   # double click / second tab
            raise _already_submitted()
        raise HTTPException(409, "Your signature changed while submitting. Please check it and submit again.")
    log.info("exit form submitted by %s", empid)
    return {"status": "submitted", "id": str(saved["_id"]), "submitted_at": now.isoformat()}


def submission_status(empid: str) -> dict:
    doc = repo.find_form(empid)
    if not doc:
        return {"status": "none", "has_draft": False, "submitted": False}
    return {"status": doc["status"], "has_draft": doc["status"] == "draft",
            "submitted": doc["status"] == "submitted", "has_signature": bool(doc.get("signature_file")),
            "updated_at": aware(doc.get("updated_at")), "submitted_at": aware(doc.get("submitted_at"))}
