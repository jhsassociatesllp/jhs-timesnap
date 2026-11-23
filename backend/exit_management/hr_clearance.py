# backend/exit_management/hr_clearance.py
"""HR Clearance (the HR stage of the approval workflow), done by the HR manager (JHS1423) from the HR Clearance form.

Same pattern as IT Clearance (it_clearance.py), with its own authorisation (approvals.hr_managers):
    Reporting Manager APPROVED + handover submitted -> IT Clearance APPROVED -> current_stage "hr" (HR Clearance Pending)
    HR manager fills the 3 rows + HR comments + signatures and submits  -> HR stage Approved, form COMPLETE
    HR manager rejects (comments required)                              -> HR stage Rejected, nothing further
The HR manager sees the submitted exit applications of EVERY employee (no team filter); the form opens only on HR's turn. Never for
their own form. Stored inside the employee's own `exist_form` document:

    hr_clearance: {approver_id, status: draft|submitted, items: [{key, particular, option, remarks, signature_file}] x3,
                   hr_comments, hr_signature_file, created_at, updated_at, submitted_at, submitted_by}

Each signature is a GridFS file in `signature_files` (metadata kind="hr_clearance"). The employee's own signature shown on the form is
the one from their submitted Exit Form.
"""
import logging

from fastapi import HTTPException, UploadFile
from pymongo import ReturnDocument
from pymongo.errors import PyMongoError

from backend.exit_management import approvals, it_clearance, manager, signature
from backend.exit_management import repository as repo
from backend.exit_management.schemas import HrPayload, RejectPayload
from backend.exit_management.utils import aware, public_form, public_signature, utcnow

log = logging.getLogger("exit_management")

ROWS = [  # (key, "Particulars" exactly as on the HR Clearance form)
    ("notice_period", "Served Notice Period"),
    ("cash_adjustment", "Any Cash/Salary/Loan Adjustment Due?"),
    ("erp_deletion", "ERP ID Deletion"),
]
ROW_KEYS = [k for k, _ in ROWS]
HR_SIGN = "hr_sign"                                        # the HR Signature slot (besides the three row signatures)
OPTIONS = ("Yes", "No")
DECLARATION = ("I hereby declare that I haven't joined any of JHS Client OR I have informed the HR Department "
               "on the Client I would be joining.")


def _db_err():
    return HTTPException(503, "Could not reach the database. Please try again.")


def _stage_text(doc: dict) -> str:
    a = doc["approval"]
    if a["hr"].get("status") == "rejected":
        return "Rejected"
    stage = a.get("current_stage")
    if stage == "rejected":
        return "Not applicable"
    if stage in ("reporting_manager", "it"):
        return "Waiting"
    if stage == "hr":
        return "Pending"
    return "Approved"


def _status_text(doc: dict, key: str) -> str:
    s = doc["approval"].get(key) or {}
    if s.get("status") == "rejected":
        return "Rejected"
    if s.get("status") == "approved":
        return "Approved"
    if key == "reporting_manager" and s.get("decision") == "approved":
        return "Approved - handover pending"
    return "Pending"


def dashboard(me: str) -> dict:
    """HR manager details and ALL submitted exit applications. Each row shows that employee's own stage statuses;
    the form can be opened for filling only when it is the HR stage's turn (after Reporting Manager, handover and IT)."""
    if me not in approvals.hr_managers():
        raise HTTPException(403, "You are not an HR manager for exit clearance.")
    emp = repo.find_employee(me) or {}
    try:
        docs = list(repo.collection.find({"status": "submitted", "employee_id": {"$ne": me},
                                          "approval": {"$exists": True}}).sort("submitted_at", -1))
    except PyMongoError:
        log.exception("hr dashboard failed")
        raise _db_err()
    rows = []
    for d in docs:
        a, det, hc = d["approval"], d.get("employee_details") or {}, d.get("hr_clearance")
        stage = a.get("current_stage")
        done = bool(hc) and hc.get("status") == "submitted"
        if done:
            note = None
        elif stage == "hr":
            note = None
        elif a["hr"].get("status") == "rejected":
            note = "Rejected by HR"
        elif stage == "rejected":
            note = "Rejected earlier in the approval process"
        elif stage == "it":
            note = "Locked until IT Clearance is approved"
        else:
            note = "Locked until the Reporting Manager approves and the handover is completed"
        rows.append({"id": str(d["_id"]), "employee_id": d.get("employee_id"), "employee_name": d.get("employee_name"),
                     "designation": det.get("designation"), "resignation_date": det.get("resignation_date"),
                     "last_working_date": det.get("last_working_date"), "submitted_at": aware(d.get("submitted_at")),
                     "reporting_manager_status": _status_text(d, "reporting_manager"), "it_status": _status_text(d, "it"),
                     "hr_status": _stage_text(d), "stage": stage,
                     "action": "view" if (done or a["hr"].get("status") == "rejected" and hc) else ("fill" if stage == "hr" else None),
                     "note": note})
    return {"manager": {"employee_id": me, "name": emp.get("Emp Name") or me, "designation": (emp.get("Designation Name") or "").strip(),
                        "branch": emp.get("Branch Name") or ""},
            "applications": rows, "total_applications": len(rows), "pending_count": sum(1 for r in rows if r["action"] == "fill")}


# ── authorisation: verified in MongoDB on every call ─────────────────────────
def _authorised(me: str, form_id: str) -> dict:
    doc = approvals.load_form(form_id)
    if me == doc.get("employee_id") or me not in approvals.scoped_hr_approvers(doc.get("employee_id")):
        raise HTTPException(403, "You are not the HR manager for this employee.")
    return doc


def _new_clearance(me: str, now) -> dict:
    return {"approver_id": me, "status": "draft", "created_at": now, "updated_at": now, "submitted_at": None, "submitted_by": None,
            "hr_comments": "", "hr_signature_file": None,
            "items": [{"key": k, "particular": label, "option": None, "remarks": "", "signature_file": None} for k, label in ROWS]}


def _open(me: str, form_id: str, *, editable: bool) -> dict:
    """The form for its HR manager. Opening it needs the HR stage to be current (Reporting Manager approved + handover + IT approved);
    a form that was already submitted (or rejected with a clearance) can still be viewed."""
    doc = _authorised(me, form_id)
    hc = doc.get("hr_clearance")
    stage = doc["approval"].get("current_stage")
    if hc is None:
        if stage != "hr":
            raise HTTPException(409, "HR Clearance is not available yet: the application is still with the Reporting Manager or IT, "
                                     "or it was rejected.")
        try:                                                     # created the first time the HR manager opens it
            repo.collection.update_one({"_id": doc["_id"], "approval.current_stage": "hr", "hr_clearance": {"$exists": False}},
                                       {"$set": {"hr_clearance": _new_clearance(me, utcnow())}})
            doc = repo.collection.find_one({"_id": doc["_id"]})
        except PyMongoError:
            log.exception("create hr clearance failed")
            raise _db_err()
        hc = doc.get("hr_clearance")
    if editable and (hc.get("status") != "draft" or doc["approval"].get("current_stage") != "hr"):
        raise HTTPException(409, "The HR Clearance form has already been completed.")
    return doc


def _view(doc: dict, me: str) -> dict:
    hc, det = doc["hr_clearance"], doc.get("employee_details") or {}
    done = hc.get("status") == "submitted"
    return {"form_id": str(doc["_id"]), "status": hc.get("status"), "submitted_at": aware(hc.get("submitted_at")),
            "editable": hc.get("status") == "draft" and doc["approval"].get("current_stage") == "hr",
            "rejected": doc["approval"]["hr"].get("status") == "rejected",
            "rejection_reason": doc["approval"]["hr"].get("rejection_reason"),
            "employee": {"name": doc.get("employee_name"), "employee_id": doc.get("employee_id"), "designation": det.get("designation"),
                         "last_working_date": det.get("last_working_date")},
            "manager_name": approvals._name_of(hc.get("submitted_by") if done else me),
            "form_date": (aware(hc.get("submitted_at")) if done else utcnow().date().isoformat())[:10],
            "declaration": DECLARATION, "hr_comments": hc.get("hr_comments") or "",
            "employee_signature": public_signature(doc.get("signature_file")),
            "hr_signature": public_signature(hc.get("hr_signature_file")),
            "items": [{"key": it["key"], "particular": it["particular"], "option": it.get("option"), "remarks": it.get("remarks") or "",
                       "signature": public_signature(it.get("signature_file"))} for it in hc["items"]]}


def get_form(me: str, form_id: str) -> dict:
    return _view(_open(me, form_id, editable=False), me)


def _clean(payload: HrPayload) -> dict:
    seen = {}
    for row in payload.items:
        if row.key not in ROW_KEYS:
            raise HTTPException(422, f"Unknown HR Clearance row '{row.key}'.")
        if row.key in seen:
            raise HTTPException(422, f"HR Clearance row '{row.key}' was sent twice.")
        seen[row.key] = row
    return seen


def _row_updates(rows: dict, comments) -> dict:
    sets = {}
    for i, key in enumerate(ROW_KEYS):
        if key in rows:
            sets[f"hr_clearance.items.{i}.option"] = rows[key].option
            sets[f"hr_clearance.items.{i}.remarks"] = (rows[key].remarks or "").strip()
    if comments is not None:
        sets["hr_clearance.hr_comments"] = comments.strip()
    return sets


def save_draft(me: str, form_id: str, payload: HrPayload) -> dict:
    doc = _open(me, form_id, editable=True)
    now = utcnow()
    try:
        res = repo.collection.update_one({"_id": doc["_id"], "hr_clearance.status": "draft"},
                                         {"$set": {**_row_updates(_clean(payload), payload.hr_comments),
                                                   "hr_clearance.updated_at": now, "updated_at": now}})
    except PyMongoError:
        log.exception("save hr clearance failed")
        raise _db_err()
    if res.matched_count == 0:
        raise HTTPException(409, "The HR Clearance form has already been completed.")
    return {"saved": True, "updated_at": now.isoformat()}


def _slot(key: str):
    """-> (document field of the signature reference, list index or None). Rows live in items[], the HR Signature slot at the top."""
    if key == HR_SIGN:
        return "hr_clearance.hr_signature_file", None
    if key in ROW_KEYS:
        return f"hr_clearance.items.{ROW_KEYS.index(key)}.signature_file", ROW_KEYS.index(key)
    raise HTTPException(404, "Unknown HR Clearance signature slot.")


def _ref_of(hc: dict, key: str):
    if key == HR_SIGN:
        return hc.get("hr_signature_file")
    items = hc.get("items") or []
    return items[ROW_KEYS.index(key)].get("signature_file") if key in ROW_KEYS and len(items) > ROW_KEYS.index(key) else None


def upload_signature(me: str, form_id: str, key: str, upload: UploadFile) -> dict:
    """Upload or replace ONE signature (a row's, or the HR Signature): PDF/JPG/JPEG/PNG, 5 MB, in GridFS."""
    field, _ = _slot(key)
    doc = _open(me, form_id, editable=True)
    new_id, ref = signature.store_upload(upload, {"employee_id": doc["employee_id"], "form_id": doc["_id"],
                                                  "kind": "hr_clearance", "row_key": key, "uploaded_by": me})
    try:
        before = repo.collection.find_one_and_update(
            {"_id": doc["_id"], "hr_clearance.status": "draft", "approval.current_stage": "hr"},
            {"$set": {field: ref, "hr_clearance.updated_at": utcnow()}}, return_document=ReturnDocument.BEFORE)
    except PyMongoError:
        log.exception("attach hr signature failed")
        signature.delete_file(new_id)
        raise _db_err()
    if before is None:
        signature.delete_file(new_id)
        raise HTTPException(409, "The HR Clearance form has already been completed.")
    old = (_ref_of(before["hr_clearance"], key) or {}).get("gridfs_file_id")
    if old and old != new_id:
        signature.delete_file(old)                               # only after the new file is safely referenced
    return public_signature(ref)


def remove_signature(me: str, form_id: str, key: str) -> dict:
    field, _ = _slot(key)
    doc = _open(me, form_id, editable=True)
    ref = _ref_of(doc["hr_clearance"], key)
    if not ref:
        raise HTTPException(404, "No signature uploaded here.")
    try:
        res = repo.collection.update_one({"_id": doc["_id"], "hr_clearance.status": "draft", f"{field}.gridfs_file_id": ref["gridfs_file_id"]},
                                         {"$set": {field: None, "hr_clearance.updated_at": utcnow()}})
    except PyMongoError:
        log.exception("remove hr signature failed")
        raise _db_err()
    if res.modified_count == 0:
        raise HTTPException(409, "The signature changed or the form was completed. Please reload the page.")
    signature.delete_file(ref["gridfs_file_id"])
    return {"deleted": True}


def view_signature(who: str, form_id: str, key: str, download: bool = False):
    """The HR manager, and the employee themself (once the clearance is submitted), may view a stored signature.
    key "employee" streams the employee's own Exit Form signature (for the HR manager)."""
    doc = approvals.load_form(form_id)
    hc = doc.get("hr_clearance") or {}
    is_owner = who == doc.get("employee_id")
    if is_owner:
        allowed = hc.get("status") == "submitted" and key != "employee"
    else:
        allowed = who in approvals.scoped_hr_approvers(doc.get("employee_id"))
    if not allowed:
        raise HTTPException(403, "You are not allowed to view this file.")
    if key == "employee":
        ref = doc.get("signature_file")
        if not ref:
            raise HTTPException(404, "No signature uploaded here.")
        return signature.stream_response(ref, lambda m: m.get("employee_id") == doc["employee_id"], download)
    _slot(key)
    ref = _ref_of(hc, key)
    if not ref:
        raise HTTPException(404, "No signature uploaded here.")
    return signature.stream_response(ref, lambda m: m.get("form_id") == doc["_id"] and m.get("row_key") == key
                                     and m.get("employee_id") == doc["employee_id"] and m.get("kind") == "hr_clearance", download)


def submit(me: str, form_id: str, payload: HrPayload) -> dict:
    """Final submit = HR stage approved AND the whole exit form complete, in ONE atomic update. Every row needs Yes/No; at least one
    signature (a row's or the HR Signature) must be a verified file."""
    doc = _open(me, form_id, editable=True)
    rows = _clean(payload)
    hc = doc["hr_clearance"]
    errors, conditions = [], {}
    for i, (key, label) in enumerate(ROWS):
        option = rows[key].option if key in rows else hc["items"][i].get("option")
        if option not in OPTIONS:
            errors.append(f"'{label}': choose Yes or No")
        elif option == "Yes" and not hc["items"][i].get("signature_file"):
            errors.append(f"'{label}': a signature is required when the answer is Yes")
    for key in (*ROW_KEYS, HR_SIGN):
        field, _ = _slot(key)
        ref = _ref_of(hc, key)
        if not ref:
            continue
        gf = signature.own_file(ref.get("gridfs_file_id"), lambda m, k=key: (
            m.get("form_id") == doc["_id"] and m.get("row_key") == k and m.get("employee_id") == doc["employee_id"]
            and m.get("kind") == "hr_clearance"))
        if gf is None or gf.length <= 0 or gf.length > signature.MAX_BYTES:
            errors.append(f"A signature file is missing or invalid - upload it again ({key})")
        else:
            conditions[f"{field}.gridfs_file_id"] = ref["gridfs_file_id"]
    if not errors and not conditions:
        errors.append("Upload at least one signature (a row's or the HR Signature)")
    if errors:
        raise HTTPException(422, {"message": "Please complete the HR Clearance form before submitting.", "errors": errors})
    now = utcnow()
    sets = {**_row_updates(rows, payload.hr_comments),
            "hr_clearance.status": "submitted", "hr_clearance.submitted_at": now, "hr_clearance.submitted_by": me,
            "hr_clearance.updated_at": now,
            "approval.hr.status": "approved", "approval.hr.approver_code": me, "approval.hr.approver_name": approvals._name_of(me),
            "approval.hr.approved_at": now, "approval.current_stage": "complete",
            "approval.form_complete.status": "approved", "approval.form_complete.completed_at": now, "updated_at": now}
    try:
        res = repo.collection.update_one(
            {"_id": doc["_id"], "status": "submitted", "approval.current_stage": "hr", "approval.hr.status": "pending",
             "hr_clearance.status": "draft", **conditions},
            {"$set": sets})
    except PyMongoError:
        log.exception("submit hr clearance failed")
        raise _db_err()
    if res.modified_count == 0:
        raise HTTPException(409, "The form changed while submitting (or was already completed). Please reload the page.")
    log.info("HR clearance for exit form %s submitted by %s: HR approved, form complete", form_id, me)
    return {"submitted": True, "next_stage": "complete"}


def reject(me: str, form_id: str, payload: RejectPayload) -> dict:
    """The HR manager rejects at the HR stage (comments required, shown to the employee). Only on HR's turn, before it is completed."""
    doc = _authorised(me, form_id)
    if doc["approval"].get("current_stage") != "hr" or (doc.get("hr_clearance") or {}).get("status") == "submitted":
        raise HTTPException(409, "HR Clearance cannot be rejected now: it is not HR's turn yet, or it was already completed.")
    now = utcnow()
    sets = {"approval.current_stage": "rejected", "approval.hr.status": "rejected", "approval.hr.rejected_at": now,
            "approval.hr.rejection_reason": payload.reason, "approval.hr.approver_code": me,
            "approval.hr.approver_name": approvals._name_of(me), "updated_at": now}
    if doc.get("hr_clearance"):
        sets["hr_clearance.hr_comments"] = payload.reason
    try:
        res = repo.collection.update_one(
            {"_id": doc["_id"], "status": "submitted", "approval.current_stage": "hr", "approval.hr.status": "pending",
             "hr_clearance.status": {"$ne": "submitted"}},
            {"$set": sets})
    except PyMongoError:
        log.exception("hr reject failed")
        raise _db_err()
    if res.modified_count == 0:
        raise HTTPException(409, "This application has already been processed. Please refresh.")
    log.info("exit form %s rejected at the HR stage by %s", form_id, me)
    return {"decision": "rejected"}


# ── read-only views for the HR manager: the employee's filled exit form and the IT Clearance form ──
def view_exit_form(me: str, form_id: str) -> dict:
    """What the employee filled in on the Exit Form (any stage). Only for an HR manager (never for the employee's own form)."""
    doc = _authorised(me, form_id)
    full = public_form(doc)
    out = {k: full.get(k) for k in ("id", "employee_id", "employee_name", "employee_details", "manager_feedback",
                                    "company_feedback", "exit_interview", "submitted_at")}
    out["signature"] = full.get("signature_file")
    return out


def exit_form_signature(me: str, form_id: str, download: bool = False):
    doc = _authorised(me, form_id)
    ref = doc.get("signature_file")
    if not ref:
        raise HTTPException(404, "No signature uploaded.")
    return signature.stream_response(ref, lambda m: m.get("employee_id") == doc["employee_id"], download)


def view_it_clearance(me: str, form_id: str) -> dict:
    """The IT Clearance form of this employee, read-only, once it has been created (IT's turn or later)."""
    doc = _authorised(me, form_id)
    if not doc.get("it_clearance"):
        raise HTTPException(409, "IT Clearance has not been started for this employee yet.")
    out = it_clearance._view(doc, me)
    out["editable"] = False                                       # HR only reads it
    return out


def view_handover(me: str, form_id: str) -> dict:
    """The Project Related Details (handover) form of this employee, read-only, once the Reporting Manager has started it."""
    doc = _authorised(me, form_id)
    ph = doc.get("project_handover")
    if not ph:
        raise HTTPException(409, "The Project Details form has not been started for this employee yet.")
    out = manager._handover_view(doc, me)
    rm = doc["approval"]["reporting_manager"]
    out["manager_name"] = approvals._name_of(ph.get("submitted_by") or rm.get("decided_by_code") or rm.get("expected_approver_code"))
    out["editable"] = False                                       # HR only reads it
    return out
