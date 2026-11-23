# backend/exit_management/it_clearance.py
"""IT Clearance (the IT stage of the approval workflow) for IT-team employees, done by their IT manager.

The IT manager is JHS722 (approvals.IT_MANAGER_TEAMS; more can be listed in `exit_approvers` rows with a `team`). The IT manager sees
the submitted exit applications of EVERY employee (no Reporting Manager / team filter) and completes the IT stage for any of them - but only
through this form and only once that employee's own Reporting Manager has approved and the handover is submitted. Nobody else
(neither the owners nor other IT approvers) can complete the IT stage.

Workflow (all inside the employee's own `exist_form` document - no second document):
    Reporting Manager APPROVED + handover submitted -> current_stage "it" (IT Clearance Pending)
    IT manager fills the 4 rows and submits         -> IT stage Approved, current_stage "hr" (HR Pending)
A rejected application (current_stage "rejected") or one still with the Reporting Manager can never be opened here.

Stored as `it_clearance: {approver_id, status: draft|submitted, items: [{key, particular, option, remarks, signature_file}]}`;
each row's signature is a GridFS file in `signature_files` (metadata kind="it_clearance").
"""
import logging

from fastapi import HTTPException, UploadFile
from pymongo import ReturnDocument
from pymongo.errors import PyMongoError

from backend.exit_management import approvals, signature
from backend.exit_management import repository as repo
from backend.exit_management.schemas import ItPayload, RejectPayload
from backend.exit_management.utils import aware, public_signature, utcnow

log = logging.getLogger("exit_management")

ROWS = [  # (key, "Particulars" exactly as on the IT Clearance form)
    ("jhs_laptop", "JHS Laptop Returned"),
    ("jhs_email_disabled", "Official JHS Email ID Disabled"),
    ("client_laptop", "Client Laptop Returned"),
    ("client_email_disabled", "Client Email ID Disabled"),
    ("nexus_quant_id", "Nexus Quant ID Disabled"),
    ("msb_portal_id", "MSB Portal ID Disabled"),
    ("work_data_handover", "All Official Work Data Handover"),
    ("personal_email_removed", "Personal Email ID & Official Email Removed from JHS Mumbai Advisory"),
    ("mobile_sim", "Mobile Number / Official SIM Returned or Deactivated (if applicable)"),
    ("biometric_access", "JHS Biometric Access Disabled"),
    ("hardware_devices", "Hardware Devices Returned (CDs, Hard Disk, Pen Drive, Dongle, Headset, etc.)"),
    ("other_it_assets", "Other IT Assets Returned"),
]
OPTIONS = ("Yes", "No", "NA")
ROW_KEYS = [k for k, _ in ROWS]


def _db_err():
    return HTTPException(503, "Could not reach the database. Please try again.")


def _stage_text(doc: dict) -> str:
    stage = doc["approval"].get("current_stage")
    if doc["approval"]["it"].get("status") == "rejected":
        return "Rejected"
    if stage == "rejected":
        return "Not applicable"
    if stage == "reporting_manager":
        return "Waiting"
    if stage == "it":
        return "Pending"
    return "Approved"


def _rm_text(doc: dict) -> str:
    """The employee's own Reporting Manager status, including the handover step."""
    rm = doc["approval"]["reporting_manager"]
    if rm.get("status") == "rejected":
        return "Rejected"
    if rm.get("status") == "approved":
        return "Approved"
    return "Approved - handover pending" if rm.get("decision") == "approved" else "Pending"


def dashboard(me: str) -> dict:
    """IT manager details and ALL submitted exit applications (any employee, whoever their Reporting Manager is).
    Each row carries that employee's own approval status; the form can be opened for filling only when it is the IT stage's turn."""
    if me not in approvals.it_managers():
        raise HTTPException(403, "You are not an IT manager for exit clearance.")
    emp = repo.find_employee(me) or {}
    try:
        docs = list(repo.collection.find({"status": "submitted", "employee_id": {"$ne": me},
                                          "approval": {"$exists": True}}).sort("submitted_at", -1))
    except PyMongoError:
        log.exception("it dashboard failed")
        raise _db_err()
    rows = []
    for d in docs:
        a, det, ic = d["approval"], d.get("employee_details") or {}, d.get("it_clearance")
        stage = a.get("current_stage")
        done = bool(ic) and ic.get("status") == "submitted"
        ph = (d.get("project_handover") or {}).get("status")
        rows.append({"id": str(d["_id"]), "employee_id": d.get("employee_id"), "employee_name": d.get("employee_name"),
                     "designation": det.get("designation"), "resignation_date": det.get("resignation_date"),
                     "last_working_date": det.get("last_working_date"), "submitted_at": aware(d.get("submitted_at")),
                     "reporting_manager_status": _rm_text(d),
                     "handover_status": "Completed" if ph == "submitted" else ("Pending" if ph else "Not started"),
                     "it_status": _stage_text(d), "stage": stage,
                     "action": "view" if done else ("fill" if stage == "it" else None),
                     "note": None if (done or stage == "it") else
                     ("Rejected by IT" if a["it"].get("status") == "rejected" else "Rejected by the Reporting Manager" if stage == "rejected"
                      else "Locked until the Reporting Manager approves and the handover is completed")})
    return {"manager": {"employee_id": me, "name": emp.get("Emp Name") or me, "designation": emp.get("Designation Name") or "",
                        "branch": emp.get("Branch Name") or "", "team_size": len(approvals.it_team_of(me))},
            "applications": rows, "total_applications": len(rows), "pending_count": sum(1 for r in rows if r["action"] == "fill")}


# ── authorisation: verified in MongoDB on every call ─────────────────────────
def _authorised(me: str, form_id: str) -> dict:
    doc = approvals.load_form(form_id)
    if me == doc.get("employee_id") or me not in approvals.scoped_it_approvers(doc.get("employee_id")):
        raise HTTPException(403, "You are not the IT manager for this employee.")
    return doc


def _new_clearance(me: str, now) -> dict:
    return {"approver_id": me, "status": "draft", "created_at": now, "updated_at": now, "submitted_at": None, "submitted_by": None,
            "items": [{"key": k, "particular": label, "option": None, "remarks": "", "signature_file": None} for k, label in ROWS]}


def _open(me: str, form_id: str, *, editable: bool) -> dict:
    """The form for its IT manager. Opening it needs the IT stage to be current (Reporting Manager approved + handover done);
    a form that was already submitted can still be viewed."""
    doc = _authorised(me, form_id)
    ic = doc.get("it_clearance")
    stage = doc["approval"].get("current_stage")
    if ic is None:
        if stage != "it":
            raise HTTPException(409, "IT Clearance is not available yet: the application was rejected or the Reporting Manager "
                                     "has not completed approval and the project handover." if stage in ("rejected", "reporting_manager")
                                else "IT Clearance is not available for this application.")
        try:                                                     # created the first time the IT manager opens it
            repo.collection.update_one({"_id": doc["_id"], "approval.current_stage": "it", "it_clearance": {"$exists": False}},
                                       {"$set": {"it_clearance": _new_clearance(me, utcnow())}})
            doc = repo.collection.find_one({"_id": doc["_id"]})
        except PyMongoError:
            log.exception("create it clearance failed")
            raise _db_err()
        ic = doc.get("it_clearance")
    if ic.get("status") == "draft" and [i.get("key") for i in ic.get("items", [])] != ROW_KEYS:
        doc = _upgrade_draft(doc)                                # a draft that still has the old questions
    if editable and (ic.get("status") != "draft" or doc["approval"].get("current_stage") != "it"):
        raise HTTPException(409, "The IT Clearance form has already been submitted.")
    return doc


def _upgrade_draft(doc: dict) -> dict:
    """Replace the items of an unsubmitted draft that was started with the old questions by the current ones
    (the old rows' signature files are removed from GridFS). Submitted forms are never touched."""
    old = [(i.get("signature_file") or {}).get("gridfs_file_id") for i in doc["it_clearance"].get("items", [])]
    fresh = _new_clearance(doc["it_clearance"].get("approver_id"), utcnow())["items"]
    try:
        res = repo.collection.update_one({"_id": doc["_id"], "it_clearance.status": "draft"},
                                         {"$set": {"it_clearance.items": fresh, "it_clearance.updated_at": utcnow()}})
    except PyMongoError:
        log.exception("upgrade it clearance draft failed")
        raise _db_err()
    if res.modified_count:
        for fid in old:
            if fid:
                signature.delete_file(fid)
    return repo.collection.find_one({"_id": doc["_id"]})


def _view(doc: dict, me: str) -> dict:
    ic, det = doc["it_clearance"], doc.get("employee_details") or {}
    done = ic.get("status") == "submitted"
    return {"form_id": str(doc["_id"]), "status": ic.get("status"), "submitted_at": aware(ic.get("submitted_at")), "editable": not done,
            "employee": {"name": doc.get("employee_name"), "employee_id": doc.get("employee_id"), "designation": det.get("designation"),
                         "last_working_date": det.get("last_working_date")},
            "manager_name": approvals._name_of(ic.get("submitted_by") if done else me),
            "form_date": (aware(ic.get("submitted_at")) if done else utcnow().date().isoformat())[:10],
            "items": [{"key": it["key"], "particular": it["particular"], "option": it.get("option"), "remarks": it.get("remarks") or "",
                       "signature": public_signature(it.get("signature_file"))} for it in ic["items"]]}


def get_form(me: str, form_id: str) -> dict:
    return _view(_open(me, form_id, editable=False), me)


def _clean(payload: ItPayload) -> dict:
    seen = {}
    for row in payload.items:
        if row.key not in ROW_KEYS:
            raise HTTPException(422, f"Unknown IT Clearance row '{row.key}'.")
        if row.key in seen:
            raise HTTPException(422, f"IT Clearance row '{row.key}' was sent twice.")
        seen[row.key] = row
    return seen


def _row_updates(rows: dict) -> dict:
    sets = {}
    for i, key in enumerate(ROW_KEYS):
        if key in rows:
            sets[f"it_clearance.items.{i}.option"] = rows[key].option
            sets[f"it_clearance.items.{i}.remarks"] = (rows[key].remarks or "").strip()
    return sets


def save_draft(me: str, form_id: str, payload: ItPayload) -> dict:
    doc = _open(me, form_id, editable=True)
    now = utcnow()
    try:
        res = repo.collection.update_one({"_id": doc["_id"], "it_clearance.status": "draft"},
                                         {"$set": {**_row_updates(_clean(payload)), "it_clearance.updated_at": now, "updated_at": now}})
    except PyMongoError:
        log.exception("save it clearance failed")
        raise _db_err()
    if res.matched_count == 0:
        raise HTTPException(409, "The IT Clearance form has already been submitted.")
    return {"saved": True, "updated_at": now.isoformat()}


def _row_index(key: str) -> int:
    if key not in ROW_KEYS:
        raise HTTPException(404, "Unknown IT Clearance row.")
    return ROW_KEYS.index(key)


def upload_row_signature(me: str, form_id: str, key: str, upload: UploadFile) -> dict:
    """Upload or replace the signature file of ONE row (PDF/JPG/JPEG/PNG, 5 MB) in GridFS."""
    idx = _row_index(key)
    doc = _open(me, form_id, editable=True)
    new_id, ref = signature.store_upload(upload, {"employee_id": doc["employee_id"], "form_id": doc["_id"],
                                                  "kind": "it_clearance", "row_key": key, "uploaded_by": me})
    field = f"it_clearance.items.{idx}.signature_file"
    try:
        before = repo.collection.find_one_and_update(
            {"_id": doc["_id"], "it_clearance.status": "draft", "approval.current_stage": "it"},
            {"$set": {field: ref, "it_clearance.updated_at": utcnow()}}, return_document=ReturnDocument.BEFORE)
    except PyMongoError:
        log.exception("attach it signature failed")
        signature.delete_file(new_id)
        raise _db_err()
    if before is None:
        signature.delete_file(new_id)
        raise HTTPException(409, "The IT Clearance form has already been submitted.")
    old = (before["it_clearance"]["items"][idx].get("signature_file") or {}).get("gridfs_file_id")
    if old and old != new_id:
        signature.delete_file(old)                               # only after the new file is safely referenced
    return public_signature(ref)


def remove_row_signature(me: str, form_id: str, key: str) -> dict:
    idx = _row_index(key)
    doc = _open(me, form_id, editable=True)
    ref = doc["it_clearance"]["items"][idx].get("signature_file")
    if not ref:
        raise HTTPException(404, "No signature uploaded for this row.")
    field = f"it_clearance.items.{idx}.signature_file"
    try:
        res = repo.collection.update_one({"_id": doc["_id"], "it_clearance.status": "draft", f"{field}.gridfs_file_id": ref["gridfs_file_id"]},
                                         {"$set": {field: None, "it_clearance.updated_at": utcnow()}})
    except PyMongoError:
        log.exception("remove it signature failed")
        raise _db_err()
    if res.modified_count == 0:
        raise HTTPException(409, "The signature changed or the form was submitted. Please reload the page.")
    signature.delete_file(ref["gridfs_file_id"])
    return {"deleted": True}


def view_row_signature(who: str, form_id: str, key: str, download: bool = False):
    """The IT manager of the employee, HR approvers, and the employee themself (after submission) may view a row's file."""
    doc = approvals.load_form(form_id)
    ic = doc.get("it_clearance") or {}
    stored = [i.get("key") for i in ic.get("items", [])]
    if key not in stored:
        raise HTTPException(404, "Unknown IT Clearance row.")
    idx = stored.index(key)
    is_owner = who == doc.get("employee_id")
    if is_owner:
        allowed = ic.get("status") == "submitted"
    else:
        allowed = (who in approvals.scoped_it_approvers(doc.get("employee_id")) or approvals._is_stage_approver(who, "hr")
                   or who in approvals.scoped_hr_approvers(doc.get("employee_id")))
    if not allowed:
        raise HTTPException(403, "You are not allowed to view this file.")
    items = ic.get("items") or []
    ref = items[idx].get("signature_file") if len(items) > idx else None
    if not ref:
        raise HTTPException(404, "No signature uploaded for this row.")
    return signature.stream_response(ref, lambda m: m.get("form_id") == doc["_id"] and m.get("row_key") == key
                                     and m.get("employee_id") == doc["employee_id"] and m.get("kind") == "it_clearance", download)


def submit(me: str, form_id: str, payload: ItPayload) -> dict:
    """Final submit = IT stage approved, HR pending, in ONE atomic update. Every row needs Yes/No; a signature file is optional
    per row but at least one row must carry a verified one."""
    doc = _open(me, form_id, editable=True)
    rows = _clean(payload)
    items = doc["it_clearance"]["items"]
    errors, conditions = [], {}
    for i, (key, label) in enumerate(ROWS):
        option = rows[key].option if key in rows else items[i].get("option")
        if option not in OPTIONS:
            errors.append(f"'{label}': choose Yes, No or NA")
        ref = items[i].get("signature_file")
        if option == "Yes" and not ref:
            errors.append(f"'{label}': a signature is required when the answer is Yes")
        if not ref:
            continue
        gf = signature.own_file(ref.get("gridfs_file_id"), lambda m, k=key: (
            m.get("form_id") == doc["_id"] and m.get("row_key") == k and m.get("employee_id") == doc["employee_id"]
            and m.get("kind") == "it_clearance"))
        if gf is None or gf.length <= 0 or gf.length > signature.MAX_BYTES:
            errors.append(f"'{label}': the signature file is missing or invalid - upload it again")
        else:
            conditions[f"it_clearance.items.{i}.signature_file.gridfs_file_id"] = ref["gridfs_file_id"]
    if not errors and not conditions:
        errors.append("Upload a signature for at least one row")
    if errors:
        raise HTTPException(422, {"message": "Please complete the IT Clearance form before submitting.", "errors": errors})
    now = utcnow()
    sets = {**(_row_updates(rows) if rows else {}),
            "it_clearance.status": "submitted", "it_clearance.submitted_at": now, "it_clearance.submitted_by": me,
            "it_clearance.updated_at": now,
            "approval.it.status": "approved", "approval.it.approver_code": me, "approval.it.approver_name": approvals._name_of(me),
            "approval.it.approved_at": now, "approval.current_stage": "hr", "approval.hr.pending_since": now, "updated_at": now}
    try:
        res = repo.collection.update_one(
            {"_id": doc["_id"], "status": "submitted", "approval.current_stage": "it", "approval.it.status": "pending",
             "it_clearance.status": "draft", **conditions},
            {"$set": sets})
    except PyMongoError:
        log.exception("submit it clearance failed")
        raise _db_err()
    if res.modified_count == 0:
        raise HTTPException(409, "The form changed while submitting (or was already submitted). Please reload the page.")
    log.info("IT clearance for exit form %s submitted by %s: IT approved, HR pending", form_id, me)
    return {"submitted": True, "next_stage": "hr"}


def reject(me: str, form_id: str, payload: RejectPayload) -> dict:
    """The IT manager rejects the application at the IT stage (reason required, shown to the employee). HR never starts.
    Only while it is IT's turn and the clearance form has not been submitted."""
    doc = _authorised(me, form_id)
    if doc["approval"].get("current_stage") != "it" or (doc.get("it_clearance") or {}).get("status") == "submitted":
        raise HTTPException(409, "IT Clearance cannot be rejected now: it is not IT's turn yet, or it was already completed.")
    now = utcnow()
    try:
        res = repo.collection.update_one(
            {"_id": doc["_id"], "status": "submitted", "approval.current_stage": "it", "approval.it.status": "pending",
             "it_clearance.status": {"$ne": "submitted"}},
            {"$set": {"approval.current_stage": "rejected", "approval.it.status": "rejected", "approval.it.rejected_at": now,
                      "approval.it.rejection_reason": payload.reason, "approval.it.approver_code": me,
                      "approval.it.approver_name": approvals._name_of(me), "updated_at": now}})
    except PyMongoError:
        log.exception("it reject failed")
        raise _db_err()
    if res.modified_count == 0:
        raise HTTPException(409, "This application has already been processed. Please refresh.")
    log.info("exit form %s rejected at the IT stage by %s", form_id, me)
    return {"decision": "rejected"}
