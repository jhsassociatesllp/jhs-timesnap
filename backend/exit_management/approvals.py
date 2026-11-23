# backend/exit_management/approvals.py
"""Approval workflow after an Exit Form is submitted:

    Reporting Manager  ->  IT  ->  HR  ->  Form Complete

The workflow lives inside the employee's own `exist_form` document (`approval` object) - no second document.
A stage can only be approved when it is the current one, so IT cannot act before the manager, HR before IT, etc.

Reporting Manager stage (handled in manager.py, from the Reporting Manager dashboard):
    decision pending -> manager Approves or Rejects the application
      * Rejected -> stage status "rejected", current_stage "rejected": nothing goes to IT or HR.
      * Approved -> the manager fills the Project Related Details (handover) form with one signature file per row;
                    only when that form is SUBMITTED does the stage become "approved" and IT becomes pending.

Who may act:
  * Reporting Manager - the manager in the employee's record (`ReportingEmpCode`, read live from Employee_details;
                        the code saved at submit time is only a fallback). If there is none, HR approvers may act instead.
  * IT / HR           - people listed in the `exit_approvers` collection, plus the two owners in EXIT_ADMINS.
  * Nobody can act on their own form.
"""
import logging

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException
from pymongo.errors import PyMongoError

from backend.exit_management import repository as repo
from backend.exit_management.utils import aware, public_form, public_signature, utcnow

log = logging.getLogger("exit_management")

STAGES = ("reporting_manager", "it", "hr")                      # approval order
LABELS = {"reporting_manager": "Reporting Manager", "it": "IT Clearance", "hr": "HR Clearance", "form_complete": "Form Complete"}
# Always allowed to approve IT and HR (same two owners as the Module Access screen), so the workflow can't get stuck.
EXIT_ADMINS = ("JHS1191", "JHS1485")


def _up(value) -> str:
    return (value or "").strip().upper()


def _name_of(empid: str) -> str:
    emp = repo.find_employee(empid) or {}
    return emp.get("Emp Name") or emp.get("EmployeeName") or emp.get("Name") or empid


def initial_approval(reporting_code: str, reporting_name: str, now) -> dict:
    """The approval object saved with a newly submitted form: Reporting Manager pending, the rest waiting."""
    blank = {"status": "pending", "approver_code": None, "approver_name": None, "approved_at": None, "pending_since": None}
    return {
        "current_stage": "reporting_manager",
        "reporting_manager": {**blank, "pending_since": now,
                              "expected_approver_code": _up(reporting_code), "expected_approver_name": reporting_name or "",
                              # the manager's decision on the application itself (before the handover form)
                              "decision": "pending", "decided_at": None, "decided_by_code": None, "decided_by_name": None,
                              "rejection_reason": None, "rejected_at": None},
        "it": dict(blank),
        "hr": dict(blank),
        "form_complete": {"status": "pending", "completed_at": None},
    }


# ── who is who ───────────────────────────────────────────────────────────────
# IT managers and their juniors, by employee ID (the employee data has no department field to derive this from).
# More can be added in the `exit_approvers` collection ({stage: "it", empid, team: [...]}); both sources are combined.
IT_MANAGER_TEAMS = {"JHS722": ("JHS1474", "JHS1551")}


def _approver_docs(empid: str, stage: str) -> list:
    try:
        return list(repo.approvers.find({"stage": stage, "empid": empid}))
    except PyMongoError:
        log.exception("approver lookup failed")
        raise HTTPException(503, "Could not reach the database. Please try again.")


def it_team_of(empid: str) -> set:
    """The employees on this IT manager's IT team (the `team` list on their IT row in `exit_approvers`); empty if none."""
    return {_up(c) for d in _approver_docs(empid, "it") for c in (d.get("team") or [])} | {_up(c) for c in IT_MANAGER_TEAMS.get(empid, ())}


def it_managers() -> set:
    """Everyone who may complete IT Clearance for any employee (never their own form): the active EmpIDs in the
    `it_clearance_approvers` collection (JHS722, JHS1474, JHS1551 to start with)."""
    try:
        return repo.it_approver_ids()
    except PyMongoError:
        log.exception("it approver lookup failed")
        raise HTTPException(503, "Could not reach the database. Please try again.")


def hr_managers() -> set:
    """Everyone who may complete HR Clearance for any employee (never their own form): the active EmpIDs in the
    `hr_clearance_approvers` collection (JHS1423 and JHS911 to start with). The owners JHS1191 / JHS1485 are NOT included:
    the HR stage is completed from the HR Clearance form."""
    try:
        return repo.hr_approver_ids()
    except PyMongoError:
        log.exception("hr approver lookup failed")
        raise HTTPException(503, "Could not reach the database. Please try again.")


def scoped_hr_approvers(employee_id: str) -> set:
    """Who may complete this employee's HR Clearance: the HR managers, never the employee themself."""
    return hr_managers() - {_up(employee_id)}


def scoped_it_approvers(employee_id: str) -> set:
    """Who may complete this employee's IT Clearance: the IT managers (never the employee themself). Only they - owners and
    general IT approvers cannot. (Empty only for an IT manager's own form, which falls back to the general IT approvers.)"""
    return it_managers() - {_up(employee_id)}


def junior_managers(employee_id: str) -> set:
    """IT managers who also act as Reporting Manager of this employee because the employee is one of their juniors."""
    fixed = {m for m, team in IT_MANAGER_TEAMS.items() if _up(employee_id) in {_up(c) for c in team}}
    try:
        return fixed | {d.get("empid") for d in repo.approvers.find({"stage": "it", "team": _up(employee_id)})}
    except PyMongoError:
        log.exception("approver lookup failed")
        raise HTTPException(503, "Could not reach the database. Please try again.")


def _is_stage_approver(empid: str, stage: str) -> bool:
    """General IT / HR membership (owners count for both). An IT manager with a `team` list is team-scoped and is NOT a general approver."""
    if empid in EXIT_ADMINS:
        return True
    return any(not d.get("team") for d in _approver_docs(empid, stage))


def team_for(empid: str) -> list:
    """Employee records of this person's team: everyone whose `ReportingEmpCode` is them, plus (for an IT manager such as JHS722)
    the juniors listed for them in IT_MANAGER_TEAMS / exit_approvers. Never the person themself."""
    team = list(repo.find_team(empid))
    have = {e.get("EmpID") for e in team}
    for code in sorted(it_team_of(empid)):
        if code != empid and code not in have:
            emp = repo.find_employee(code)
            if emp:
                team.append(emp)
    return sorted(team, key=lambda e: e.get("Emp Name") or "")


def manager_code_for(doc: dict) -> str:
    """The employee's Reporting Manager: read LIVE from Employee_details (so a changed reporting line is respected);
    the code saved at submit time is used only if the record has none."""
    emp = repo.find_employee(doc.get("employee_id")) or {}
    live = _up(emp.get("ReportingEmpCode"))
    if live:
        return live
    return _up(((doc.get("approval") or {}).get("reporting_manager") or {}).get("expected_approver_code"))


def can_approve(empid: str, doc: dict, stage: str) -> bool:
    """May `empid` act on `stage` of this form? (Never their own form.)"""
    if empid == doc.get("employee_id"):
        return False
    if stage == "reporting_manager":
        code = manager_code_for(doc)
        if code:
            # the manager in the employee's record, or (for an IT-team junior) their IT manager, who is also a Reporting Manager
            return empid == code or empid in junior_managers(doc.get("employee_id"))
        return _is_stage_approver(empid, "hr")                  # no manager on record: HR steps in
    if stage == "it":
        owners = scoped_it_approvers(doc.get("employee_id"))
        if owners:                                              # an IT-team employee: only their IT manager (e.g. JHS722)
            return empid in owners
        return _is_stage_approver(empid, "it")
    if stage == "hr":
        return empid in scoped_hr_approvers(doc.get("employee_id"))
    return False


def roles(empid: str) -> dict:
    """Which roles this signed-in employee has (drives the navbar links)."""
    try:
        team = team_for(empid)
        pending = 0
        if team:
            pending = repo.collection.count_documents({
                "status": "submitted", "employee_id": {"$in": [e.get("EmpID") for e in team]},
                "approval.current_stage": "reporting_manager"})
    except PyMongoError:
        raise HTTPException(503, "Could not reach the database. Please try again.")
    it, hr = _is_stage_approver(empid, "it"), _is_stage_approver(empid, "hr")
    it_team = it_team_of(empid)
    is_it_mgr = empid in it_managers()
    is_hr_mgr = empid in hr_managers()
    return {"is_reporting_manager": bool(team), "team_size": len(team), "pending_applications": pending,
            "is_it": it, "is_hr": hr, "is_approver": it or hr,
            "is_it_manager": is_it_mgr, "it_team_size": len(it_team), "is_hr_manager": is_hr_mgr}


# ── employee: own tracker ────────────────────────────────────────────────────
def _stage_view(approval: dict, key: str) -> dict:
    s = approval.get(key) or {}
    current = approval.get("current_stage")
    rejected_flow = current == "rejected"
    status = s.get("status")
    if status == "rejected":
        state = "rejected"
    elif status == "approved":
        state = "done"
    elif key == current:
        state = "active"
    elif rejected_flow:
        state = "blocked"                                        # the application was rejected: this stage never happens
    else:
        state = "waiting"
    detail = None
    if key == "reporting_manager" and state == "active":
        detail = ("Application approved by the Reporting Manager - project handover form is being completed"
                  if s.get("decision") == "approved" else None)
    return {"key": key, "label": LABELS[key], "status": status if status in ("approved", "rejected") else "pending",
            "state": state, "detail": detail,
            "approver_name": s.get("approver_name"), "approver_code": s.get("approver_code"),
            "expected_approver_name": s.get("expected_approver_name"),
            "decision": s.get("decision"), "decided_at": aware(s.get("decided_at")),
            "rejection_reason": s.get("rejection_reason") if status == "rejected" else None,
            "rejected_at": aware(s.get("rejected_at")),
            "pending_since": aware(s.get("pending_since")),
            "approved_at": aware(s.get("approved_at") or s.get("completed_at"))}


def tracker_view(doc: dict) -> list:
    return [_stage_view(doc["approval"], k) for k in (*STAGES, "form_complete")]


def tracker(empid: str) -> dict:
    """The signed-in employee's own approval status."""
    doc = repo.find_form(empid)
    if not doc or doc.get("status") != "submitted":
        return {"submitted": False}
    approval = doc.get("approval")
    out = {"submitted": True, "employee_name": doc.get("employee_name"), "submitted_at": aware(doc.get("submitted_at")),
           "approval_available": bool(approval)}
    if not approval:
        return out
    out["current_stage"] = approval.get("current_stage")
    out["complete"] = approval.get("current_stage") == "complete"
    out["rejected"] = approval.get("current_stage") == "rejected"
    out["stages"] = tracker_view(doc)
    out["it_clearance"] = it_clearance_summary(doc)
    return out


# ── IT / HR: queue, review, approve ──────────────────────────────────────────
def _queue_filter(empid: str, role: dict) -> dict:
    """Forms currently waiting for an IT / HR approval this person may give.
    (The Reporting Manager stage is handled on the manager dashboard, see manager.py.)"""
    clauses = []
    if role["is_it"]:                                            # general IT approvers never see IT-team employees (their IT manager does)
        clauses.append({"approval.current_stage": "it", "employee_id": {"$in": [m for m in it_managers() if not (it_managers() - {m})]}})   # only a lone IT manager's own form needs a general approver
    if not clauses:                                              # the HR stage is completed from the HR Clearance form, not this queue
        return {"_id": {"$in": []}}
    return {"status": "submitted", "employee_id": {"$ne": empid}, "$or": clauses}


def queue(empid: str) -> list:
    role = roles(empid)
    if not role["is_approver"]:
        raise HTTPException(403, "You are not an IT or HR approver for exit forms.")
    rows = []
    for d in repo.collection.find(_queue_filter(empid, role)).sort("submitted_at", 1).limit(200):
        stage = d["approval"]["current_stage"]
        det = d.get("employee_details") or {}
        rows.append({"id": str(d["_id"]), "employee_id": d.get("employee_id"), "employee_name": d.get("employee_name"),
                     "designation": det.get("designation"), "last_working_date": det.get("last_working_date"),
                     "stage": stage, "stage_label": LABELS[stage], "submitted_at": aware(d.get("submitted_at")),
                     "pending_since": aware(d["approval"][stage].get("pending_since"))})
    return rows


def load_form(form_id: str) -> dict:
    """A submitted form that has an approval workflow, by id (404 otherwise)."""
    try:
        oid = ObjectId(form_id)
    except (InvalidId, TypeError):
        raise HTTPException(404, "Exit form not found.")
    doc = repo.collection.find_one({"_id": oid, "status": "submitted"})
    if not doc or not doc.get("approval"):
        raise HTTPException(404, "Exit form not found.")
    return doc


def handover_summary(doc: dict):
    """The project handover form as read-only JSON for IT / HR reviewers (None until the manager approved)."""
    ph = doc.get("project_handover")
    if not ph:
        return None
    return {"status": ph.get("status"), "submitted_at": aware(ph.get("submitted_at")),
            "items": [{"key": it.get("key"), "particular": it.get("particular"), "option": it.get("option"),
                       "remarks": it.get("remarks"), "signature": public_signature(it.get("signature_file"))}
                      for it in ph.get("items", [])]}


def it_clearance_summary(doc: dict):
    """The IT Clearance form as read-only JSON (None if there is none). Shown to the employee on their tracker once submitted."""
    ic = doc.get("it_clearance")
    if not ic:
        return None
    done = ic.get("status") == "submitted"
    return {"status": ic.get("status"), "submitted_at": aware(ic.get("submitted_at")), "approver_id": ic.get("approver_id"),
            "items": [{"key": it.get("key"), "particular": it.get("particular"),
                       "option": it.get("option") if done else None, "remarks": (it.get("remarks") or "") if done else "",
                       "has_signature": bool(it.get("signature_file")) if done else False}
                      for it in ic.get("items", [])]}


def review(empid: str, form_id: str) -> dict:
    """A submitted form for IT / HR. Everyone with authority over some stage sees the clearance details;
    the feedback sections (ratings about the manager and JHS, interview answers) are for HR only."""
    doc = load_form(form_id)
    if empid == doc["employee_id"]:
        raise HTTPException(403, "You cannot review your own exit form here.")
    if not (any(can_approve(empid, doc, s) for s in STAGES) or _is_stage_approver(empid, "hr")):
        raise HTTPException(403, "You are not an approver for this exit form.")
    full = public_form(doc)
    stage = doc["approval"]["current_stage"]
    sees_feedback = _is_stage_approver(empid, "hr")
    out = {k: full.get(k) for k in ("id", "employee_id", "employee_name", "employee_details", "status", "submitted_at")}
    out["stages"] = tracker_view(doc)
    out["current_stage"] = stage
    out["can_approve_now"] = stage in ("it", "hr") and can_approve(empid, doc, stage)
    out["feedback_visible"] = sees_feedback
    out["project_handover"] = handover_summary(doc)
    out["it_clearance"] = it_clearance_summary(doc)
    if sees_feedback:
        out.update({k: full.get(k) for k in ("manager_feedback", "company_feedback", "exit_interview")})
    return out


def approve(empid: str, form_id: str) -> dict:
    """Approve the form's CURRENT IT / HR stage. One atomic update that only succeeds while that stage is still pending."""
    doc = load_form(form_id)
    stage = doc["approval"].get("current_stage")
    if stage == "rejected":
        raise HTTPException(409, "This exit application was rejected.")
    if stage == "reporting_manager":
        raise HTTPException(409, "The Reporting Manager stage is completed from the Reporting Manager dashboard "
                                 "(approve the application, then submit the project handover form).")
    if stage not in STAGES:
        raise HTTPException(409, "This exit form is already complete.")
    if empid == doc["employee_id"]:
        raise HTTPException(403, "You cannot approve your own exit form.")
    if not can_approve(empid, doc, stage):
        raise HTTPException(403, f"You are not authorised to approve the {LABELS[stage]} stage of this form.")
    if stage == "it" and scoped_it_approvers(doc["employee_id"]):
        raise HTTPException(409, "IT Clearance for this employee is completed with the IT Clearance form (IT Clearance dashboard).")
    if stage == "hr":
        raise HTTPException(409, "HR Clearance is completed with the HR Clearance form (HR Clearance dashboard).")
    now = utcnow()
    changes = {f"approval.{stage}.status": "approved", f"approval.{stage}.approver_code": empid,
               f"approval.{stage}.approver_name": _name_of(empid), f"approval.{stage}.approved_at": now, "updated_at": now}
    nxt = STAGES[STAGES.index(stage) + 1] if stage != STAGES[-1] else None
    if nxt:
        changes["approval.current_stage"] = nxt
        changes[f"approval.{nxt}.pending_since"] = now
    else:                                                         # HR approved: the whole form is complete
        changes["approval.current_stage"] = "complete"
        changes["approval.form_complete.status"] = "approved"
        changes["approval.form_complete.completed_at"] = now
    try:
        res = repo.collection.update_one(
            {"_id": doc["_id"], "status": "submitted", "approval.current_stage": stage, f"approval.{stage}.status": "pending"},
            {"$set": changes})
    except PyMongoError:
        log.exception("approve failed")
        raise HTTPException(503, "Could not reach the database. Please try again.")
    if res.modified_count == 0:                                   # someone else approved it a moment ago
        raise HTTPException(409, "This stage was already processed. Please refresh.")
    log.info("exit form %s: %s approved by %s", form_id, stage, empid)
    return {"approved_stage": stage, "next_stage": nxt or "complete", "complete": nxt is None}
