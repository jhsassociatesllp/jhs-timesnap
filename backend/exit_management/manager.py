# backend/exit_management/manager.py
"""Reporting Manager dashboard and the Project Related Details (handover) form.

Detection is automatic: the signed-in employee is a Reporting Manager when other employees have their code in
`Employee_details.ReportingEmpCode`. Nothing is hardcoded and the browser never says who the manager is.

An exit application can be acted on only by the manager in the employee's record (checked live against
Employee_details on every action - see approvals.can_approve):

    pending --Reject (reason)--> rejected            (tracker shows Rejected; IT and HR never start)
    pending --Approve----------> approved decision   (project handover form is created)
    handover form SUBMITTED ---> Reporting Manager stage Approved, IT becomes Pending

Everything is stored inside the employee's own `exist_form` document:
    approval.reporting_manager.{decision, decided_at, rejection_reason, ...}   and   project_handover.{status, items[...]}
Each handover row keeps its own signature file reference (a GridFS file in `signature_files`).
"""
import logging

from fastapi import HTTPException, UploadFile
from pymongo import ReturnDocument
from pymongo.errors import PyMongoError

from backend.exit_management import approvals, signature
from backend.exit_management import repository as repo
from backend.exit_management.schemas import HandoverPayload, RejectPayload
from backend.exit_management.utils import aware, public_form, public_signature, to_iso_date, utcnow

log = logging.getLogger("exit_management")

ROWS = [  # (key, "Particulars" exactly as on the paper form)
    ("confidential_files", "Return of all confidential files and information"),
    ("project_handover", "Project Related Details Handover"),
    ("induction", "Induction given to the replacement (if any)"),
    ("other_comments", "Any other comments"),
]
ROW_KEYS = [k for k, _ in ROWS]


def _db_err():
    return HTTPException(503, "Could not reach the database. Please try again.")


def _dept(emp: dict) -> str:
    """No department field exists in Employee_details today; if one is ever added it is picked up here."""
    return emp.get("Department") or emp.get("Department Name") or ""


def _emp_row(emp: dict) -> dict:
    return {"employee_id": emp.get("EmpID"), "name": emp.get("Emp Name") or emp.get("EmployeeName") or emp.get("Name") or "",
            "designation": emp.get("Designation Name") or emp.get("Designation") or "", "department": _dept(emp),
            "branch": emp.get("Branch Name") or "", "joining_date": to_iso_date(emp.get("Date of Joining"))}


def _unassigned_for(me: str) -> list:
    """Submitted forms of employees with NO reporting manager on record: HR approvers handle those instead."""
    if not approvals._is_stage_approver(me, "hr"):
        return []
    docs = repo.collection.find({"status": "submitted", "approval.current_stage": "reporting_manager",
                                 "approval.reporting_manager.expected_approver_code": "", "employee_id": {"$ne": me}})
    return [d for d in docs if not approvals.manager_code_for(d)]


def _application_status(doc: dict) -> str:
    a = doc["approval"]
    rm = a["reporting_manager"]
    stage = a.get("current_stage")
    if stage == "rejected":
        return "Rejected"
    if stage == "complete":
        return "Completed"
    if stage == "reporting_manager":
        return "Approved - handover form pending" if rm.get("decision") == "approved" else "Pending your review"
    return {"it": "With IT", "hr": "With HR"}.get(stage, stage)


def _application_row(doc: dict) -> dict:
    a = doc["approval"]
    rm = a["reporting_manager"]
    det = doc.get("employee_details") or {}
    stage = a.get("current_stage")
    decision = rm.get("decision") or "pending"
    return {"id": str(doc["_id"]), "employee_id": doc.get("employee_id"), "employee_name": doc.get("employee_name"),
            "designation": det.get("designation"), "resignation_date": det.get("resignation_date"),
            "last_working_date": det.get("last_working_date"), "submitted_at": aware(doc.get("submitted_at")),
            "application_status": _application_status(doc), "decision": decision, "stage": stage,
            "rejection_reason": rm.get("rejection_reason"),
            "can_decide": stage == "reporting_manager" and decision == "pending",
            "can_handover": stage == "reporting_manager" and decision == "approved"}


def dashboard(me: str) -> dict:
    """Manager details, the team, and the submitted exit applications of that team (and only that team)."""
    emp = repo.find_employee(me)
    if not emp:
        raise HTTPException(404, "Your employee record was not found. Please contact HR.")
    try:
        team = approvals.team_for(me)
        extra = _unassigned_for(me)
        if not team and not extra:
            raise HTTPException(403, "You are not a Reporting Manager: no employee reports to you.")
        ids = [e.get("EmpID") for e in team]
        docs = list(repo.collection.find({"status": "submitted", "employee_id": {"$in": ids}, "approval": {"$exists": True}})
                    .sort("submitted_at", -1)) + extra
    except PyMongoError:
        log.exception("manager dashboard failed")
        raise _db_err()
    submitted_ids = {d.get("employee_id") for d in docs}
    members = []
    for e in team:
        row = _emp_row(e)
        row["has_exit_application"] = row["employee_id"] in submitted_ids
        members.append(row)
    me_row = _emp_row(emp)
    return {"manager": {**me_row, "total_team_members": len(team), "department_available": bool(me_row["department"])},
            "team": members,
            "applications": [_application_row(d) | ({"unassigned": True} if d in extra else {}) for d in docs],
            "pending_count": sum(1 for d in docs if d["approval"]["current_stage"] == "reporting_manager")}


# ── authorisation: the manager is verified in MongoDB on every action ────────
def _authorised(me: str, form_id: str) -> dict:
    doc = approvals.load_form(form_id)
    if not approvals.can_approve(me, doc, "reporting_manager"):
        raise HTTPException(403, "You are not the Reporting Manager of this employee.")
    return doc


def _rm(doc: dict) -> dict:
    return doc["approval"]["reporting_manager"]


def reject(me: str, form_id: str, payload: RejectPayload) -> dict:
    doc = _authorised(me, form_id)
    if doc["approval"].get("current_stage") != "reporting_manager" or (_rm(doc).get("decision") or "pending") != "pending":
        raise HTTPException(409, "This application has already been decided.")
    now = utcnow()
    try:
        res = repo.collection.update_one(
            {"_id": doc["_id"], "status": "submitted", "approval.current_stage": "reporting_manager",
             "approval.reporting_manager.decision": {"$in": ["pending", None]}},
            {"$set": {"approval.current_stage": "rejected", "approval.reporting_manager.status": "rejected",
                      "approval.reporting_manager.decision": "rejected", "approval.reporting_manager.decided_at": now,
                      "approval.reporting_manager.rejected_at": now, "approval.reporting_manager.rejection_reason": payload.reason,
                      "approval.reporting_manager.decided_by_code": me,
                      "approval.reporting_manager.decided_by_name": approvals._name_of(me), "updated_at": now}})
    except PyMongoError:
        log.exception("reject failed")
        raise _db_err()
    if res.modified_count == 0:
        raise HTTPException(409, "This application has already been decided. Please refresh.")
    log.info("exit form %s rejected by %s", form_id, me)
    return {"decision": "rejected"}


def approve(me: str, form_id: str) -> dict:
    """Approve the application: the handover form is created. The Reporting Manager STAGE stays pending until it is submitted."""
    doc = _authorised(me, form_id)
    if doc["approval"].get("current_stage") != "reporting_manager" or (_rm(doc).get("decision") or "pending") != "pending":
        raise HTTPException(409, "This application has already been decided.")
    now = utcnow()
    handover = {"status": "draft", "created_at": now, "updated_at": now, "submitted_at": None, "submitted_by": None,
                "items": [{"key": k, "particular": label, "option": None, "remarks": "", "signature_file": None} for k, label in ROWS]}
    try:
        res = repo.collection.update_one(
            {"_id": doc["_id"], "status": "submitted", "approval.current_stage": "reporting_manager",
             "approval.reporting_manager.decision": {"$in": ["pending", None]}},
            {"$set": {"approval.reporting_manager.decision": "approved", "approval.reporting_manager.decided_at": now,
                      "approval.reporting_manager.decided_by_code": me,
                      "approval.reporting_manager.decided_by_name": approvals._name_of(me),
                      "project_handover": handover, "updated_at": now}})
    except PyMongoError:
        log.exception("approve failed")
        raise _db_err()
    if res.modified_count == 0:
        raise HTTPException(409, "This application has already been decided. Please refresh.")
    log.info("exit form %s approved (handover form opened) by %s", form_id, me)
    return {"decision": "approved", "form_id": form_id}


# ── project handover form ────────────────────────────────────────────────────
def _open_handover(me: str, form_id: str, *, editable: bool) -> dict:
    """The form for its Reporting Manager. `editable` = it must still be a draft (not yet submitted)."""
    doc = _authorised(me, form_id)
    ph = doc.get("project_handover")
    if (_rm(doc).get("decision") != "approved") or not ph:
        raise HTTPException(409, "Approve the application first to open the project handover form.")
    if editable and (ph.get("status") != "draft" or doc["approval"].get("current_stage") != "reporting_manager"):
        raise HTTPException(409, "The project handover form has already been submitted.")
    return doc


def _handover_view(doc: dict, me: str) -> dict:
    ph = doc["project_handover"]
    det = doc.get("employee_details") or {}
    submitted = ph.get("status") == "submitted"
    return {"form_id": str(doc["_id"]), "status": ph.get("status"), "submitted_at": aware(ph.get("submitted_at")),
            "employee": {"name": doc.get("employee_name"), "employee_id": doc.get("employee_id"),
                         "designation": det.get("designation"), "joining_date": det.get("joining_date"),
                         "last_working_date": det.get("last_working_date")},
            "manager_name": approvals._name_of(me),
            "form_date": (aware(ph.get("submitted_at")) if submitted else utcnow().date().isoformat())[:10],
            "editable": not submitted,
            "items": [{"key": it["key"], "particular": it["particular"], "option": it.get("option"),
                       "remarks": it.get("remarks") or "", "signature": public_signature(it.get("signature_file"))}
                      for it in ph["items"]]}


def get_handover(me: str, form_id: str) -> dict:
    return _handover_view(_open_handover(me, form_id, editable=False), me)


def _clean_items(payload: HandoverPayload) -> dict:
    seen = {}
    for row in payload.items:
        if row.key not in ROW_KEYS:
            raise HTTPException(422, f"Unknown handover row '{row.key}'.")
        if row.key in seen:
            raise HTTPException(422, f"Handover row '{row.key}' was sent twice.")
        seen[row.key] = row
    return seen


def _row_updates(rows: dict) -> dict:
    sets = {}
    for i, key in enumerate(ROW_KEYS):
        if key in rows:
            sets[f"project_handover.items.{i}.option"] = rows[key].option
            sets[f"project_handover.items.{i}.remarks"] = (rows[key].remarks or "").strip()
    return sets


def save_handover(me: str, form_id: str, payload: HandoverPayload) -> dict:
    """Save Draft: the Yes/No choices and remarks (signatures are uploaded per row, separately)."""
    doc = _open_handover(me, form_id, editable=True)
    now = utcnow()
    sets = {**_row_updates(_clean_items(payload)), "project_handover.updated_at": now, "updated_at": now}
    try:
        res = repo.collection.update_one({"_id": doc["_id"], "project_handover.status": "draft"}, {"$set": sets})
    except PyMongoError:
        log.exception("save handover failed")
        raise _db_err()
    if res.matched_count == 0:
        raise HTTPException(409, "The project handover form has already been submitted.")
    return {"saved": True, "updated_at": now.isoformat()}


def _row_index(key: str) -> int:
    if key not in ROW_KEYS:
        raise HTTPException(404, "Unknown handover row.")
    return ROW_KEYS.index(key)


def upload_row_signature(me: str, form_id: str, key: str, upload: UploadFile) -> dict:
    """Upload or replace the signature file of ONE row (PDF/JPG/JPEG/PNG, 5 MB) in GridFS."""
    idx = _row_index(key)
    doc = _open_handover(me, form_id, editable=True)
    new_id, ref = signature.store_upload(upload, {"employee_id": doc["employee_id"], "form_id": doc["_id"],
                                                  "kind": "handover", "row_key": key, "uploaded_by": me})
    field = f"project_handover.items.{idx}.signature_file"
    try:
        before = repo.collection.find_one_and_update(
            {"_id": doc["_id"], "project_handover.status": "draft", "approval.current_stage": "reporting_manager"},
            {"$set": {field: ref, "project_handover.updated_at": utcnow()}}, return_document=ReturnDocument.BEFORE)
    except PyMongoError:
        log.exception("attach row signature failed")
        signature.delete_file(new_id)
        raise _db_err()
    if before is None:                                   # submitted in the meantime
        signature.delete_file(new_id)
        raise HTTPException(409, "The project handover form has already been submitted.")
    old = (before["project_handover"]["items"][idx].get("signature_file") or {}).get("gridfs_file_id")
    if old and old != new_id:
        signature.delete_file(old)                       # only after the new file is safely referenced
    return public_signature(ref)


def remove_row_signature(me: str, form_id: str, key: str) -> dict:
    """Cancel/remove the signature of ONE row (never after the handover form is submitted)."""
    idx = _row_index(key)
    doc = _open_handover(me, form_id, editable=True)
    ref = doc["project_handover"]["items"][idx].get("signature_file")
    if not ref:
        raise HTTPException(404, "No signature uploaded for this row.")
    field = f"project_handover.items.{idx}.signature_file"
    try:
        res = repo.collection.update_one(
            {"_id": doc["_id"], "project_handover.status": "draft", f"{field}.gridfs_file_id": ref["gridfs_file_id"]},
            {"$set": {field: None, "project_handover.updated_at": utcnow()}})
    except PyMongoError:
        log.exception("remove row signature failed")
        raise _db_err()
    if res.modified_count == 0:
        raise HTTPException(409, "The signature changed or the form was submitted. Please reload the page.")
    signature.delete_file(ref["gridfs_file_id"])
    return {"deleted": True}


def view_row_signature(who: str, form_id: str, key: str, download: bool = False):
    """The stored signature file of one row: for the form's Reporting Manager, and for IT / HR reviewers."""
    idx = _row_index(key)
    doc = approvals.load_form(form_id)
    allowed = (approvals.can_approve(who, doc, "reporting_manager") or any(approvals._is_stage_approver(who, s) for s in ("it", "hr"))
               or who in approvals.scoped_hr_approvers(doc.get("employee_id")))
    if who == doc.get("employee_id") or not allowed:
        raise HTTPException(403, "You are not allowed to view this file.")
    items = (doc.get("project_handover") or {}).get("items") or []
    ref = items[idx].get("signature_file") if len(items) > idx else None
    if not ref:
        raise HTTPException(404, "No signature uploaded for this row.")
    return signature.stream_response(ref, lambda m: m.get("form_id") == doc["_id"] and m.get("row_key") == key
                                     and m.get("employee_id") == doc["employee_id"], download)


def submit_handover(me: str, form_id: str, payload: HandoverPayload) -> dict:
    """Final submit: all four rows need a Yes/No; a signature is optional per row but at least one row must carry a verified signature file. Only then does the Reporting Manager
    stage become Approved and IT become Pending - in ONE atomic update."""
    doc = _open_handover(me, form_id, editable=True)
    rows = _clean_items(payload)
    items = doc["project_handover"]["items"]
    errors, conditions = [], {}
    for i, (key, label) in enumerate(ROWS):
        incoming = rows.get(key)
        option = incoming.option if incoming else items[i].get("option")
        if option not in ("Yes", "No"):
            errors.append(f"'{label}': choose Yes or No")
        ref = items[i].get("signature_file")
        if option == "Yes" and not ref:
            errors.append(f"'{label}': a signature is required when the answer is Yes")
        gf = signature.own_file(ref.get("gridfs_file_id"), lambda m, k=key: (
            m.get("form_id") == doc["_id"] and m.get("row_key") == k and m.get("employee_id") == doc["employee_id"])) if ref else None
        if not ref:
            continue                                     # a row may be left unsigned (its signature box was not ticked)
        if gf is None or gf.length <= 0 or gf.length > signature.MAX_BYTES:
            errors.append(f"'{label}': the signature file is missing or invalid - upload it again")
        else:
            conditions[f"project_handover.items.{i}.signature_file.gridfs_file_id"] = ref["gridfs_file_id"]
    if not errors and not conditions:
        errors.append("Upload your signature and tick it for at least one row")
    if errors:
        raise HTTPException(422, {"message": "Please complete the project handover form before submitting.", "errors": errors})
    now = utcnow()
    sets = {**(_row_updates(rows) if rows else {}),
            "project_handover.status": "submitted", "project_handover.submitted_at": now,
            "project_handover.submitted_by": me, "project_handover.updated_at": now,
            "approval.reporting_manager.status": "approved", "approval.reporting_manager.approver_code": me,
            "approval.reporting_manager.approver_name": approvals._name_of(me), "approval.reporting_manager.approved_at": now,
            "approval.current_stage": "it", "approval.it.pending_since": now, "updated_at": now}
    try:
        res = repo.collection.update_one(
            {"_id": doc["_id"], "status": "submitted", "approval.current_stage": "reporting_manager",
             "approval.reporting_manager.decision": "approved", "project_handover.status": "draft", **conditions},
            {"$set": sets})
    except PyMongoError:
        log.exception("submit handover failed")
        raise _db_err()
    if res.modified_count == 0:
        raise HTTPException(409, "The form changed while submitting (or was already submitted). Please reload the page.")
    log.info("handover submitted for exit form %s by %s: Reporting Manager approved, IT pending", form_id, me)
    return {"submitted": True, "next_stage": "it"}


# ── the employee's own exit form, read-only, for their Reporting Manager ─────
def view_exit_form(me: str, form_id: str) -> dict:
    """What the employee filled in on the Exit Form (details, dates, ratings, interview answers, signature reference).
    Only the Reporting Manager of that employee (verified live in MongoDB) may read it."""
    doc = _authorised(me, form_id)
    full = public_form(doc)
    out = {k: full.get(k) for k in ("id", "employee_id", "employee_name", "employee_details", "manager_feedback",
                                    "company_feedback", "exit_interview", "submitted_at")}
    out["signature"] = full.get("signature_file")
    return out


def exit_form_signature(me: str, form_id: str, download: bool = False):
    """The employee's own signature file from their Exit Form, for their Reporting Manager."""
    doc = _authorised(me, form_id)
    ref = doc.get("signature_file")
    if not ref:
        raise HTTPException(404, "No signature uploaded.")
    return signature.stream_response(ref, lambda m: m.get("employee_id") == doc["employee_id"], download)
