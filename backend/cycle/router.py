# backend/cycle/router.py
"""
10-day cycle review. Roles (checked on EVERY endpoint, per employee / per project):
  manager = reporting manager of the employee (Employee_details.ReportingEmpCode == user)
  admin   = has_admin_module(user, "timesheet"): any employee, unlock, any project
  employee = nothing here

Approving LOCKS the employee's cycle: entries become approved+locked, and the daily timesheet
refuses any further change (even new entries on empty days) via backend.cycle.locks.
"""
import html as _h
from datetime import date, datetime, timedelta
from typing import List, Optional

import pytz
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from backend import mailer
from backend.access_manager.router import has_admin_module
from backend.auth import get_current_user
from backend.cycle import digest
from backend.cycle.store import config_doc, holidays_set, store
from backend.nq import repository as nq_repo
from backend.nq.models import NQUnavailable
from backend.timesheet import project_health, rules

router = APIRouter(prefix="/timesheet/v2/cycles", tags=["Cycle review"])
IST = pytz.timezone("Asia/Kolkata")
MAX_BATCH = 200


# ─────────────────────────────── roles ───────────────────────────────────────

def _me(user: str) -> str:
    return (user or "").strip().upper()


def _is_admin(me: str) -> bool:
    return has_admin_module(me, "timesheet")


def _reportees(manager: str) -> List[str]:
    return [d["EmpID"].strip().upper() for d in
            store.employees.find({"ReportingEmpCode": manager}, {"EmpID": 1}) if d.get("EmpID")]


def _manages(me: str, employee_id: str, admin: bool) -> bool:
    if admin:
        return True
    doc = store.employees.find_one({"EmpID": employee_id}, {"ReportingEmpCode": 1}) or {}
    return (doc.get("ReportingEmpCode") or "").strip().upper() == me


def _today() -> date:
    return datetime.now(IST).date()


def _cycle(cycle_id: str) -> rules.Cycle:
    try:
        return rules.cycle_from_id(cycle_id)
    except ValueError:
        raise HTTPException(400, "Bad cycle id (expected e.g. 2026-10-C2)")


def _employee_ids(raw: List[str]) -> List[str]:
    ids = sorted({str(e).strip().upper() for e in raw if str(e).strip()})
    if not ids:
        raise HTTPException(422, "Select at least one employee")
    if len(ids) > MAX_BATCH:
        raise HTTPException(422, f"At most {MAX_BATCH} employees per request")
    return ids


def _authorise_all(me: str, ids: List[str], admin: bool) -> None:
    bad = [i for i in ids if not _manages(me, i, admin)]
    if bad:
        raise HTTPException(403, "You are not the reporting manager of: " + ", ".join(bad))


# ─────────────────────────── team table ──────────────────────────────────────

def _employee_row(emp: str, name: str, cyc: rules.Cycle, today: date, holidays: set) -> dict:
    start, end = cyc.start.isoformat(), cyc.end.isoformat()
    off_days = {h["date"] for h in store.hrms.find(
        {"employee_id": emp, "date": {"$gte": start, "$lte": end}, "leave_flag": True}, {"date": 1})}
    required, d = [], cyc.start
    while d <= min(cyc.end, today):
        iso = d.isoformat()
        if d.weekday() < 5 and iso not in holidays and iso not in off_days:
            required.append(iso)
        d += timedelta(days=1)
    submitted = {s["date"] for s in store.submissions.find(
        {"employee_id": emp, "date": {"$gte": start, "$lte": end}}, {"date": 1})}
    missing = [x for x in required if x not in submitted]
    entries = list(store.entries.find({"employee_id": emp, "cycle_id": cyc.id}, {"hours": 1, "is_unplanned": 1}))
    hrms_hours = round(sum(h.get("net_hours") or 0 for h in store.hrms.find(
        {"employee_id": emp, "date": {"$gte": start, "$lte": end}}, {"net_hours": 1})), 2)
    reco_open = store.reco.count_documents({
        "employee_id": emp, "date": {"$gte": start, "$lte": end},
        "result": {"$in": ["short", "over", "no_punch", "not_filled"]}, "status": "open"})
    review = store.reviews.find_one({"kind": "approval", "employee_id": emp, "cycle_id": cyc.id}) or {}
    warnings = []
    if missing:
        warnings.append(f"{len(missing)} day(s) not submitted")
    if reco_open:
        warnings.append(f"{reco_open} open hours gap(s)")
    return {
        "employee_id": emp, "employee_name": name, "days_required": len(required),
        "days_filled": len(required) - len(missing), "missing_dates": missing[:31],
        "hrms_hours": hrms_hours,
        "timesheet_hours": round(sum(e["hours"] for e in entries if e.get("hours") is not None), 2),
        "unplanned": sum(1 for e in entries if e.get("is_unplanned")), "reco_gaps": reco_open,
        "status": review.get("status", "pending"), "approved_by": review.get("approved_by"),
        "approved_at": review.get("approved_at"), "warnings": warnings,
    }


def _team_ids(me: str, admin: bool, manager: Optional[str]) -> List[str]:
    pilot = {str(e).strip().upper() for e in config_doc().get("pilot_employees", []) or []}
    if admin:
        ids = _reportees(manager.strip().upper()) if manager else sorted(pilot)
    else:
        ids = _reportees(me)
        if not ids:
            raise HTTPException(403, "Only managers and admins can review cycles")
    return [i for i in ids if i in pilot]


# ─────────────────────────────── routes ──────────────────────────────────────

@router.get("/{cycle_id}/team")
def team(cycle_id: str, manager: Optional[str] = None, current_user: str = Depends(get_current_user)):
    me = _me(current_user)
    admin = _is_admin(me)
    cyc = _cycle(cycle_id)
    ids = _team_ids(me, admin, manager)
    names = {d["EmpID"].strip().upper(): d.get("Emp Name", "") for d in
             store.employees.find({"EmpID": {"$in": ids}}, {"EmpID": 1, "Emp Name": 1}) if d.get("EmpID")}
    today, hol = _today(), holidays_set()
    return {"cycle": {"id": cyc.id, "label": cyc.label, "start": cyc.start, "end": cyc.end,
                      "deadline": cyc.deadline, "past_deadline": today > cyc.deadline},
            "rows": [_employee_row(i, names.get(i, ""), cyc, today, hol) for i in ids],
            "is_admin": admin}


class ApproveIn(BaseModel):
    employee_ids: List[str]
    confirm_warnings: bool = False


@router.post("/{cycle_id}/approve")
def approve(cycle_id: str, body: ApproveIn, current_user: str = Depends(get_current_user)):
    """Approve and LOCK the cycle for each employee. If anyone still has unsubmitted days or
    open hours gaps, nothing is changed (409) until the caller repeats with confirm_warnings."""
    me = _me(current_user)
    admin = _is_admin(me)
    cyc = _cycle(cycle_id)
    ids = _employee_ids(body.employee_ids)
    _authorise_all(me, ids, admin)
    today, hol = _today(), holidays_set()
    if today <= cyc.end:
        # locking mid-cycle would stop employees filling the days they have not worked yet
        raise HTTPException(422, f"This cycle ends on {cyc.end.isoformat()} - approve it after it has ended")
    pilot = {str(e).strip().upper() for e in config_doc().get("pilot_employees", []) or []}

    rows = {}
    for i in ids:
        if i not in pilot:
            raise HTTPException(422, f"{i} is not on the daily timesheet")
        if not store.entries.find_one({"employee_id": i, "cycle_id": cyc.id}, {"_id": 1}):
            raise HTTPException(422, f"{i} has no entries in this cycle")
        rows[i] = _employee_row(i, "", cyc, today, hol)
    flagged = {i: r["warnings"] for i, r in rows.items() if r["warnings"]}
    if flagged and not body.confirm_warnings:
        raise HTTPException(409, {"message": "Some employees have open items - confirm to approve anyway",
                                  "warnings": flagged})
    now = datetime.utcnow()
    for i in ids:
        store.entries.update_many({"employee_id": i, "cycle_id": cyc.id},
                                  {"$set": {"approved": True, "locked": True, "approved_by": me, "approved_at": now}})
        store.reviews.update_one(
            {"kind": "approval", "employee_id": i, "cycle_id": cyc.id},
            {"$set": {"status": "approved", "approved_by": me, "approved_at": now,
                      "warnings_confirmed": bool(flagged.get(i))},
             "$push": {"history": {"action": "approved", "by": me, "at": now, "warnings": flagged.get(i, [])}}},
            upsert=True)
    return {"approved": ids, "warnings_confirmed": sorted(flagged)}


class UnlockIn(BaseModel):
    employee_id: str
    reason: str = Field(..., min_length=3, max_length=500)


@router.post("/{cycle_id}/unlock")
def unlock(cycle_id: str, body: UnlockIn, current_user: str = Depends(get_current_user)):
    """ADMIN ONLY: reopen an approved cycle so the employee can correct it (audited)."""
    me = _me(current_user)
    if not _is_admin(me):
        raise HTTPException(403, "Only an admin can unlock an approved cycle")
    cyc = _cycle(cycle_id)
    emp = body.employee_id.strip().upper()
    review = store.reviews.find_one({"kind": "approval", "employee_id": emp, "cycle_id": cyc.id, "status": "approved"})
    if not review:
        raise HTTPException(404, "That cycle is not approved for this employee")
    now = datetime.utcnow()
    store.entries.update_many({"employee_id": emp, "cycle_id": cyc.id}, {"$set": {"approved": False, "locked": False}})
    store.reviews.update_one({"_id": review["_id"]}, {
        "$set": {"status": "reopened", "reopened_by": me, "reopened_at": now},
        "$push": {"history": {"action": "unlocked", "by": me, "at": now, "reason": body.reason.strip()}}})
    return {"employee_id": emp, "status": "reopened"}


class RemindIn(BaseModel):
    employee_ids: List[str]


@router.post("/{cycle_id}/remind")
def remind(cycle_id: str, body: RemindIn, current_user: str = Depends(get_current_user)):
    """Email employees who still have unsubmitted days. At most one reminder per employee per day."""
    me = _me(current_user)
    admin = _is_admin(me)
    cyc = _cycle(cycle_id)
    ids = _employee_ids(body.employee_ids)
    _authorise_all(me, ids, admin)
    today, hol = _today(), holidays_set()
    digest.ensure_indexes()
    sent, skipped = [], []
    for i in ids:
        doc = store.employees.find_one({"EmpID": i}, {"Emp Name": 1, "EMail": 1}) or {}
        row = _employee_row(i, doc.get("Emp Name", ""), cyc, today, hol)
        if not row["missing_dates"]:
            skipped.append({"employee_id": i, "reason": "nothing pending"})
            continue
        to = (doc.get("EMail") or "").strip()
        if not mailer.valid_address(to):
            skipped.append({"employee_id": i, "reason": "no valid EMail"})
            continue
        shown = ", ".join(row["missing_dates"][:10]) + (" ..." if len(row["missing_dates"]) > 10 else "")
        subject = f"Timesheet reminder - {len(row['missing_dates'])} day(s) pending ({cyc.label})"
        text = (f"Hello,\n\nYour timesheet for cycle {cyc.label} still has {len(row['missing_dates'])} day(s) "
                f"to submit: {shown}.\nThe filling deadline is {cyc.deadline.isoformat()}.\n\nThank you.")
        body_html = (f"<p>Hello,</p><p>Your timesheet for cycle <b>{_h.escape(cyc.label)}</b> still has "
                     f"<b>{len(row['missing_dates'])}</b> day(s) to submit: {_h.escape(shown)}.</p>"
                     f"<p>The filling deadline is <b>{cyc.deadline.isoformat()}</b>.</p><p>Thank you.</p>")
        status = digest.deliver(f"reminder:{i}:{cyc.id}:{today.isoformat()}",
                                {"kind": "reminder", "employee_id": i, "cycle_id": cyc.id,
                                 "requested_by": me, "date": today.isoformat()},
                                [to], subject, text, body_html)
        (sent if status == "sent" else skipped).append(
            {"employee_id": i, "status": status} if status != "sent" else i)
    return {"sent": sent, "skipped": skipped}


# ─────────────────────────── re-estimate (amber / red only) ──────────────────

def _managed_projects(me: str, admin: bool, manager: Optional[str]):
    target = (manager or me).strip().upper()
    if target != me and not admin:
        raise HTTPException(403, "You can only see your own projects")
    try:
        return nq_repo.list_projects_for_manager(target)
    except NQUnavailable:
        raise HTTPException(503, "Project data is unavailable right now - please try again shortly")


@router.get("/{cycle_id}/at-risk")
def at_risk(cycle_id: str, manager: Optional[str] = None, current_user: str = Depends(get_current_user)):
    me = _me(current_user)
    admin = _is_admin(me)
    _cycle(cycle_id)
    today = _today()
    out = []
    for p in _managed_projects(me, admin, manager):
        try:
            h = project_health.compute(p.project_code, today)
        except NQUnavailable:
            raise HTTPException(503, "Project data is unavailable right now - please try again shortly")
        if not h or h["rag"] == "green":
            continue
        out.append({**{k: v for k, v in h.items() if k != "open_tasks"},
                    "tasks": [{"task_id": t.id, "name": t.name, "end_date": t.end_date, "status": t.status,
                               "is_overdue": bool(t.end_date and t.end_date < today)}
                              for t in h["open_tasks"]][:200]})
    out.sort(key=lambda r: (r["rag"] != "red", r["project_code"]))
    return {"projects": out, "writeback_enabled": bool(config_doc().get("nq_writeback_enabled", False))}


class ReestimateIn(BaseModel):
    task_id: int
    hours_needed: float = Field(..., ge=0, le=10000)
    new_end_date: date
    note: str = Field("", max_length=500)


@router.post("/{cycle_id}/reestimate")
def reestimate(cycle_id: str, body: ReestimateIn, current_user: str = Depends(get_current_user)):
    """Record hours-still-needed and a new end date for a task of an AMBER/RED project the caller
    manages (or any, for an admin). The date is written back to NQ only if write-back is enabled."""
    me = _me(current_user)
    admin = _is_admin(me)
    cyc = _cycle(cycle_id)
    today = _today()
    if not (today <= body.new_end_date <= today + timedelta(days=730)):
        raise HTTPException(422, "New end date must be between today and two years from now")
    try:
        task = nq_repo.get_task(body.task_id)
        if task is None or task.is_complete:
            raise HTTPException(404, "Open task not found")
        if not admin and task.project_code not in {p.project_code for p in _managed_projects(me, False, None)}:
            raise HTTPException(403, "You do not manage this task's project")
        health = project_health.compute(task.project_code, today)
    except NQUnavailable:
        raise HTTPException(503, "Project data is unavailable right now - please try again shortly")
    if not health or health["rag"] == "green":
        raise HTTPException(422, "Re-estimates are only for amber or red projects")

    wb_on = bool(config_doc().get("nq_writeback_enabled", False))
    record = store.reviews.insert_one({
        "kind": "reestimate", "cycle_id": cyc.id, "task_id": task.id, "project_code": task.project_code,
        "old_end_date": task.end_date.isoformat() if task.end_date else None,
        "new_end_date": body.new_end_date.isoformat(), "hours_needed": body.hours_needed,
        "note": body.note.strip(), "rag_at_time": health["rag"], "requested_by": me,
        "requested_at": datetime.utcnow(), "writeback_enabled": wb_on, "written_back": False,
        "writeback_error": ""})
    # the audit row above exists before anything changes in NQ, so a crash cannot leave an unaudited change
    written, error = False, ""
    if wb_on and body.new_end_date != task.end_date:
        try:
            written = nq_repo.update_task_end_date(task.id, body.new_end_date) == 1
        except NQUnavailable as e:
            error = str(e)[:200]
        store.reviews.update_one({"_id": record.inserted_id},
                                 {"$set": {"written_back": written, "writeback_error": error}})
    return {"task_id": task.id, "rag": health["rag"], "written_back": written, "writeback_enabled": wb_on,
            "writeback_error": error}
