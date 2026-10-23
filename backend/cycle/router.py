# backend/cycle/router.py
"""
10-day cycle review. Roles (checked on EVERY endpoint, per employee / per project):
  manager = reporting manager of the employee (Employee_details.ReportingEmpCode == user)
  admin   = has_admin_module(user, "timesheet"): any employee, unlock, any project
  employee = nothing here

Approving LOCKS the employee's cycle: entries become approved+locked, and the daily timesheet
refuses any further change (even new entries on empty days) via backend.cycle.locks, then the cycle is
mirrored into the classic Timesheet_data (backend.cycle.mirror). Sending a cycle back reopens it for the
employee (with the manager's note) until it is approved.
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
from backend.cycle import digest, mirror
from backend.cycle.store import config_doc, holidays_set, pilot_set, store
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
    resubmitted = False
    if review.get("status") == "sent_back" and review.get("sent_back_at"):
        resubmitted = store.submissions.count_documents(
            {"employee_id": emp, "cycle_id": cyc.id, "submitted_at": {"$gt": review["sent_back_at"]}}, limit=1) > 0
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
        "note": review.get("note") if review.get("status") == "sent_back" else None,
        "resubmitted": resubmitted, "mirror": (review.get("mirror") or {}).get("status"),
    }


def _team_ids(me: str, admin: bool, manager: Optional[str]) -> List[str]:
    pilot = pilot_set()
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
    note: str = Field("", max_length=500)                # optional remark kept with the approval


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
    pilot = pilot_set()

    rows = {}
    for i in ids:
        if i not in pilot:
            raise HTTPException(422, f"{i} is not on the daily timesheet")
        if not (store.entries.find_one({"employee_id": i, "cycle_id": cyc.id}, {"_id": 1})
                or store.submissions.find_one({"employee_id": i, "cycle_id": cyc.id}, {"_id": 1})):
            raise HTTPException(422, f"{i} has no entries or submitted days in this cycle")
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
             "$unset": {"note": "", "sent_back_at": "", "sent_back_by": ""},
             "$push": {"history": {"action": "approved", "by": me, "at": now, "warnings": flagged.get(i, []),
                                   **({"note": body.note.strip()} if body.note.strip() else {})}}},
            upsert=True)
    # the lock above is what matters; a failed copy to the classic collection is recorded and can be re-run
    mirror_failed = []
    for i in ids:
        result = _run_mirror(i, cyc, me)
        if result["status"] not in ("ok", "no_payroll_cycle"):
            mirror_failed.append(i)
    return {"approved": ids, "warnings_confirmed": sorted(flagged), "mirror_failed": mirror_failed}


def _run_mirror(emp: str, cyc: rules.Cycle, me: str) -> dict:
    try:
        name = (store.employees.find_one({"EmpID": me}, {"Emp Name": 1}) or {}).get("Emp Name", "")
        result = mirror.write(emp, cyc, me, name)
    except Exception as exc:                                                    # never undo an approval over this
        result = {"status": "error", "error": str(exc)[:300]}
    store.reviews.update_one({"kind": "approval", "employee_id": emp, "cycle_id": cyc.id},
                             {"$set": {"mirror": {**result, "at": datetime.utcnow()}}})
    return result


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
    try:
        mirror.remove(emp, cyc)
    except Exception as exc:
        store.reviews.update_one({"_id": review["_id"]}, {"$set": {"mirror": {"status": "error", "error": str(exc)[:300],
                                                                              "at": datetime.utcnow()}}})
    return {"employee_id": emp, "status": "reopened"}


class MirrorIn(BaseModel):
    employee_id: str


@router.post("/{cycle_id}/mirror")
def remirror(cycle_id: str, body: MirrorIn, current_user: str = Depends(get_current_user)):
    """ADMIN ONLY: run the copy to the classic timesheet again for an approved cycle (safe to repeat)."""
    me = _me(current_user)
    if not _is_admin(me):
        raise HTTPException(403, "Only an admin can re-run the mirror")
    cyc = _cycle(cycle_id)
    emp = body.employee_id.strip().upper()
    if not store.reviews.find_one({"kind": "approval", "employee_id": emp, "cycle_id": cyc.id, "status": "approved"}):
        raise HTTPException(404, "That cycle is not approved for this employee")
    return _run_mirror(emp, cyc, me)


class SendBackIn(BaseModel):
    employee_id: str
    note: str = Field(..., min_length=3, max_length=500)


@router.post("/{cycle_id}/send-back")
def send_back(cycle_id: str, body: SendBackIn, current_user: str = Depends(get_current_user)):
    """Reopen an employee's cycle for corrections, with a note they see on their timesheet. The reporting
    manager (or an admin) only. An APPROVED cycle must be unlocked by an admin first."""
    me = _me(current_user)
    admin = _is_admin(me)
    cyc = _cycle(cycle_id)
    emp = body.employee_id.strip().upper()
    _authorise_all(me, [emp], admin)
    if emp not in pilot_set():
        raise HTTPException(422, f"{emp} is not on the daily timesheet")
    if _today() <= cyc.end:
        raise HTTPException(422, f"This cycle ends on {cyc.end.isoformat()} - review it after it has ended")
    key = {"kind": "approval", "employee_id": emp, "cycle_id": cyc.id}
    if store.reviews.find_one({**key, "status": "approved"}):
        raise HTTPException(409, "This cycle is approved and locked - ask an admin to unlock it first")
    now = datetime.utcnow()
    note = body.note.strip()
    store.reviews.update_one(key, {
        "$set": {"status": "sent_back", "note": note, "sent_back_by": me, "sent_back_at": now},
        "$push": {"history": {"action": "sent_back", "by": me, "at": now, "note": note}}}, upsert=True)
    return {"employee_id": emp, "status": "sent_back"}


def _task_summary(emp: str, cyc: rules.Cycle):
    """Per task the employee worked on in this cycle: hours this cycle, hours so far on the task, and the hours
    allotted to it (working days x 8.5, from its Nexus Quant dates). Unplanned work is one extra line."""
    rows = list(store.entries.find({"employee_id": emp, "cycle_id": cyc.id, "hours": {"$ne": None}},
                                   {"task_id": 1, "task_name": 1, "client": 1, "project": 1, "project_code": 1, "hours": 1,
                                    "task_status": 1, "is_unplanned": 1, "date": 1}).sort("date", 1))
    ids = sorted({r["task_id"] for r in rows if r.get("task_id") is not None})
    used = {x["_id"]: round(x["h"], 2) for x in store.entries.aggregate([
        {"$match": {"employee_id": emp, "task_id": {"$in": ids}, "hours": {"$ne": None}}},
        {"$group": {"_id": "$task_id", "h": {"$sum": "$hours"}}}])} if ids else {}
    nq, nq_down = {}, False
    if ids:
        try:
            nq = {t.id: t for t in nq_repo.get_tasks_by_ids(ids)}
        except NQUnavailable:
            nq_down = True
    hol = {date.fromisoformat(h) for h in holidays_set()}
    by: dict = {}
    for r in rows:
        key = r["task_id"] if r.get("task_id") is not None else "unplanned"
        g = by.setdefault(key, {"task_id": r.get("task_id"), "task_name": r.get("task_name") or ("Unplanned work" if key == "unplanned" else ""),
                                "client": r.get("client") or "", "project": r.get("project") or "", "project_code": r.get("project_code") or "",
                                "cycle_hours": 0.0, "rows": 0, "days": set(), "last_status": None})
        g["cycle_hours"] += r["hours"]; g["rows"] += 1; g["days"].add(r["date"]); g["last_status"] = r.get("task_status")
    out = []
    for key, g in by.items():
        t = nq.get(key) if key != "unplanned" else None
        budget = rules.budget_hours(t.start_date, t.end_date, hol) if t else None
        total = used.get(key) if key != "unplanned" else None
        out.append({**{k: v for k, v in g.items() if k != "days"}, "days": len(g["days"]), "cycle_hours": round(g["cycle_hours"], 2),
                    "hours_so_far": total, "allotted_hours": budget,
                    "pct_used": round(100 * total / budget) if (budget and total is not None) else None,
                    "over_allotted": bool(budget and total is not None and total > budget),
                    "task_start": t.start_date if t else None, "task_end": t.end_date if t else None})
    out.sort(key=lambda x: (x["task_id"] is None, -x["cycle_hours"]))
    return out, nq_down


@router.get("/{cycle_id}/employee/{employee_id}")
def employee_detail(cycle_id: str, employee_id: str, current_user: str = Depends(get_current_user)):
    """Day-by-day rows of one employee for the review screen. Reporting manager or admin only."""
    me = _me(current_user)
    admin = _is_admin(me)
    cyc = _cycle(cycle_id)
    emp = employee_id.strip().upper()
    _authorise_all(me, [emp], admin)
    if emp not in pilot_set():
        raise HTTPException(422, f"{emp} is not on the daily timesheet")
    start, end = cyc.start.isoformat(), cyc.end.isoformat()
    subs = {x["date"]: x for x in store.submissions.find({"employee_id": emp, "date": {"$gte": start, "$lte": end}})}
    drafts = {x["date"]: x for x in store.drafts.find({"employee_id": emp, "date": {"$gte": start, "$lte": end}})}
    by_day: dict = {}
    for e in store.entries.find({"employee_id": emp, "cycle_id": cyc.id}).sort("created_at", 1):
        by_day.setdefault(e["date"], []).append(e)
    hol, today = holidays_set(), _today()
    days, d = [], cyc.start
    while d <= cyc.end:
        iso = d.isoformat()
        rows = by_day.get(iso, [])
        sub = subs.get(iso)
        loc = (sub or drafts.get(iso) or {}).get("location") or (rows[0].get("location") if rows else None)
        working = d.weekday() < 5 and iso not in hol
        days.append({
            "date": iso, "weekday": d.strftime("%a"), "working_day": working, "location": loc,
            "state": "submitted" if sub else ("saved" if rows or iso in drafts else ("missing" if working and d <= today else "none")),
            "hours": round(sum(r["hours"] for r in rows if r.get("hours") is not None), 2),
            "entries": [{"task_name": r.get("task_name") or "", "client": r.get("client") or "",
                         "project": r.get("project") or "", "project_code": r.get("project_code") or "",
                         "remarks": r.get("remarks") or "", "hours": r.get("hours"),
                         "task_status": r.get("task_status"), "is_unplanned": bool(r.get("is_unplanned")),
                         "extra_remarks": r.get("extra_remarks") or ""}
                        for r in rows]})
        d += timedelta(days=1)
    name = (store.employees.find_one({"EmpID": emp}, {"Emp Name": 1}) or {}).get("Emp Name", "")
    review = store.reviews.find_one({"kind": "approval", "employee_id": emp, "cycle_id": cyc.id}) or {}
    row = _employee_row(emp, name, cyc, today, hol)
    tasks, nq_down = _task_summary(emp, cyc)
    return {"cycle": {"id": cyc.id, "label": cyc.label, "start": cyc.start, "end": cyc.end, "deadline": cyc.deadline},
            "employee": row, "days": days, "tasks": tasks, "nq_unavailable": nq_down,
            "history": [{"action": h.get("action"), "by": h.get("by"), "at": h.get("at"),
                         "note": h.get("note") or h.get("reason")} for h in review.get("history", [])][-20:]}


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
