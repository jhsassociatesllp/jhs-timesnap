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
from backend.hrms import rules as hrms_rules
from backend.nq import repository as nq_repo
from backend.nq.models import NQUnavailable
from backend.timesheet import payrolls, project_health, rules

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


def _configured_cycle(cycle_id: str) -> rules.Cycle:
    """A cycle an ADMIN has created (Admin setup), with the admin's deadline. Anything else is not reviewable."""
    cyc = _cycle(cycle_id)
    if not payrolls.is_configured(cyc.id):
        raise HTTPException(404, "That cycle has not been created by an admin yet")
    return payrolls.effective_cycle_by_id(cyc.id)


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

GAP_RESULTS = ("short", "over", "no_punch", "not_filled")


def _compare_day(h: Optional[dict], typed: float, n_rows: int, st: dict) -> dict:
    """Typed hours of one day against the HRMS row of that day (gross hours stored at upload; net = gross - lunch)."""
    if not h:
        return {"has_data": False}
    kind = h.get("kind") or hrms_rules.classify(h.get("status_code"))
    gross = h.get("gross_hours")
    net = hrms_rules.net_from_gross(gross, st["lunch_hours"])
    result = hrms_rules.reco_result(kind, n_rows, typed, net, st["tolerance_hours"])
    return {"has_data": True, "status_code": h.get("status_code"), "kind": kind, "in_time": h.get("in_time"),
            "out_time": h.get("out_time"), "gross_hours": gross, "net_hours": net, "typed_hours": round(typed, 2),
            "diff": round(typed - net, 2) if (kind == "working" and net is not None) else None, "result": result}


def _hrms_and_typed(emp: str, cyc: rules.Cycle, st: dict):
    """({date: hrms row}, {date: (typed hours, rows with hours)}) for the cycle: two small queries."""
    start, end = cyc.start.isoformat(), cyc.end.isoformat()
    hrms = {h["date"]: h for h in store.hrms.find({"employee_id": emp, "date": {"$gte": start, "$lte": end}},
                                                  {"date": 1, "kind": 1, "status_code": 1, "in_time": 1, "out_time": 1,
                                                   "gross_hours": 1, "leave_flag": 1})}
    typed: dict = {}
    for r in store.entries.find({"employee_id": emp, "cycle_id": cyc.id, "hours": {"$ne": None}}, {"date": 1, "hours": 1}):
        t = typed.setdefault(r["date"], [0.0, 0])
        t[0] += r["hours"]; t[1] += 1
    return hrms, {d: (v[0], v[1]) for d, v in typed.items()}


def _employee_row(emp: str, name: str, cyc: rules.Cycle, today: date, holidays: set,
                  week_off=rules.WEEK_OFF_DEFAULT, st: Optional[dict] = None) -> dict:
    st = st or payrolls.settings()
    start, end = cyc.start.isoformat(), cyc.end.isoformat()
    hrms_by_day, typed_by_day = _hrms_and_typed(emp, cyc, st)
    off_days = {d for d, h in hrms_by_day.items() if h.get("leave_flag")}
    required, d = [], cyc.start
    while d <= min(cyc.end, today):
        iso = d.isoformat()
        if d.weekday() not in week_off and iso not in holidays and iso not in off_days:
            required.append(iso)
        d += timedelta(days=1)
    submitted = {s["date"] for s in store.submissions.find(
        {"employee_id": emp, "date": {"$gte": start, "$lte": end}}, {"date": 1})}
    missing = [x for x in required if x not in submitted]
    entries = list(store.entries.find({"employee_id": emp, "cycle_id": cyc.id}, {"hours": 1, "is_unplanned": 1}))
    hrms_hours, diff_hours, reco_open = 0.0, 0.0, 0
    for day, h in hrms_by_day.items():
        typed, n = typed_by_day.get(day, (0.0, 0))
        c = _compare_day(h, typed, n, st)
        if c["kind"] == "working" and c["net_hours"] is not None:
            hrms_hours += c["net_hours"]
            diff_hours += typed - c["net_hours"]
        if c["result"] in GAP_RESULTS:
            reco_open += 1
    hrms_hours, diff_hours = round(hrms_hours, 2), round(diff_hours, 2)
    review = store.reviews.find_one({"kind": "approval", "employee_id": emp, "cycle_id": cyc.id}) or {}
    resubmitted = False
    if review.get("status") == "sent_back" and review.get("sent_back_at"):
        resubmitted = store.submissions.count_documents(
            {"employee_id": emp, "cycle_id": cyc.id, "submitted_at": {"$gt": review["sent_back_at"]}}, limit=1) > 0
    warnings = []
    if missing:
        warnings.append(f"{len(missing)} day(s) not submitted")
    if reco_open:
        warnings.append(f"{reco_open} day(s) where typed hours differ from HRMS")
    return {
        "employee_id": emp, "employee_name": name, "days_required": len(required),
        "days_filled": len(required) - len(missing), "missing_dates": missing[:31],
        "hrms_hours": hrms_hours, "diff_hours": diff_hours,
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

@router.get("/payrolls")
def payroll_list(current_user: str = Depends(get_current_user)):
    """The payrolls and sub-cycles the admin created (newest first), for the Review team drop-down."""
    me = _me(current_user)
    if not _is_admin(me) and not _reportees(me):
        raise HTTPException(403, "Only managers and admins can review cycles")
    today = _today()
    out = []
    for p in payrolls.list_payrolls():
        out.append({"id": p["_id"], "label": p["label"], "cycles": [
            {"id": c["id"], "label": c["label"], "start": c["start"], "end": c["end"], "deadline": c["deadline"],
             "ended": date.fromisoformat(c["end"]) < today, "current": c["start"] <= today.isoformat() <= c["end"]}
            for c in p["cycles"]]})
    return {"payrolls": out, "today": today.isoformat()}


@router.get("/{cycle_id}/team")
def team(cycle_id: str, manager: Optional[str] = None, current_user: str = Depends(get_current_user)):
    me = _me(current_user)
    admin = _is_admin(me)
    cyc = _configured_cycle(cycle_id)
    ids = _team_ids(me, admin, manager)
    names = {d["EmpID"].strip().upper(): d.get("Emp Name", "") for d in
             store.employees.find({"EmpID": {"$in": ids}}, {"EmpID": 1, "Emp Name": 1}) if d.get("EmpID")}
    today, hol, st = _today(), holidays_set(), payrolls.settings()
    return {"cycle": {"id": cyc.id, "label": cyc.label, "start": cyc.start, "end": cyc.end,
                      "deadline": cyc.deadline, "past_deadline": today > cyc.deadline},
            "rows": [_employee_row(i, names.get(i, ""), cyc, today, hol, st["week_off"], st) for i in ids],
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
    cyc = _configured_cycle(cycle_id)
    ids = _employee_ids(body.employee_ids)
    _authorise_all(me, ids, admin)
    today, hol, st = _today(), holidays_set(), payrolls.settings()
    pilot = pilot_set()

    rows = {}
    for i in ids:
        if i not in pilot:
            raise HTTPException(422, f"{i} is not on the daily timesheet")
        if not (store.entries.find_one({"employee_id": i, "cycle_id": cyc.id}, {"_id": 1})
                or store.submissions.find_one({"employee_id": i, "cycle_id": cyc.id}, {"_id": 1})):
            raise HTTPException(422, f"{i} has no entries or submitted days in this cycle")
        rows[i] = _employee_row(i, "", cyc, today, hol, st["week_off"], st)
        if today <= cyc.end:                       # approving early locks the days the employee has not filled yet
            rows[i]["warnings"].append(f"the cycle has not ended (it ends on {cyc.end.isoformat()}): the employee cannot fill any more days after approval")
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
    cyc = _configured_cycle(cycle_id)
    emp = body.employee_id.strip().upper()
    _authorise_all(me, [emp], admin)
    if emp not in pilot_set():
        raise HTTPException(422, f"{emp} is not on the daily timesheet")
    key = {"kind": "approval", "employee_id": emp, "cycle_id": cyc.id}
    if store.reviews.find_one({**key, "status": "approved"}):
        raise HTTPException(409, "This cycle is approved and locked - ask an admin to unlock it first")
    now = datetime.utcnow()
    note = body.note.strip()
    store.reviews.update_one(key, {
        "$set": {"status": "sent_back", "note": note, "sent_back_by": me, "sent_back_at": now},
        "$push": {"history": {"action": "sent_back", "by": me, "at": now, "note": note}}}, upsert=True)
    return {"employee_id": emp, "status": "sent_back"}


def _verdict(e: dict, total: float, allotted) -> str:
    """How a row stands against the hours allotted to its task (allotted = working days of the task x hours per day)."""
    if e.get("task_id") is None or e.get("is_unplanned"):
        return "unplanned"
    if allotted is None:
        return "unknown"
    within = round(total, 2) <= round(allotted, 2)
    if e.get("task_status") == "done":
        return "completed_within" if within else "completed_over"
    return "in_progress_within" if within else "in_progress_over"


def _review_rows(emp: str, cyc: rules.Cycle, st: dict):
    """Every entry of the cycle, in date order, enriched with the hours on its task so far, the hours allotted to the task
    (from its Nexus Quant start/end dates, excluding week-off days and holidays) and a verdict. Also the NQ-down flag."""
    rows = list(store.entries.find({"employee_id": emp, "cycle_id": cyc.id}).sort([("date", 1), ("created_at", 1)]))
    ids = sorted({r["task_id"] for r in rows if r.get("task_id") is not None})
    before = {x["_id"]: x["h"] for x in store.entries.aggregate([
        {"$match": {"employee_id": emp, "task_id": {"$in": ids}, "hours": {"$ne": None}, "date": {"$lt": cyc.start.isoformat()}}},
        {"$group": {"_id": "$task_id", "h": {"$sum": "$hours"}}}])} if ids else {}
    nq, nq_down = {}, False
    if ids:
        try:
            nq = {t.id: t for t in nq_repo.get_tasks_by_ids(ids)}
        except NQUnavailable:
            nq_down = True
    hol = set(st["holidays"])
    allotted = {tid: rules.budget_hours(t.start_date, t.end_date, hol, standard_hours=st["standard_hours"], week_off=st["week_off"])
                for tid, t in nq.items()}
    running = dict(before)
    out = []
    for r in rows:
        tid = r.get("task_id")
        if tid is not None and r.get("hours") is not None:
            running[tid] = running.get(tid, 0.0) + r["hours"]
        total = running.get(tid, 0.0) if tid is not None else None
        allot = allotted.get(tid) if tid is not None else None
        t = nq.get(tid) if tid is not None else None
        out.append({"date": r["date"], "task_id": tid, "task_name": r.get("task_name") or ("Unplanned work" if tid is None else ""),
                    "client": r.get("client") or "", "project": r.get("project") or "", "project_code": r.get("project_code") or "",
                    "hours": r.get("hours"), "task_status": r.get("task_status"), "is_unplanned": bool(r.get("is_unplanned")),
                    "remarks": r.get("remarks") or "", "extra_remarks": r.get("extra_remarks") or "",
                    "total_on_task": round(total, 2) if total is not None else None, "allotted_hours": allot,
                    "allotted_days": rules.working_days(t.start_date, t.end_date, hol, st["week_off"]) if t and t.start_date and t.end_date else None,
                    "task_start": t.start_date if t else None, "task_end": t.end_date if t else None,
                    "verdict": _verdict(r, total or 0.0, allot), "location": r.get("location")})
    return out, nq_down


def _task_rollup(rows: List[dict]):
    """One line per task for the cycle (hours this cycle, hours so far, allotted, final verdict) and the counts."""
    by: dict = {}
    for r in rows:
        if r["hours"] is None:
            continue
        key = r["task_id"] if r["task_id"] is not None else "unplanned"
        g = by.setdefault(key, {"task_id": r["task_id"], "task_name": r["task_name"], "client": r["client"], "project": r["project"],
                                "project_code": r["project_code"], "cycle_hours": 0.0, "rows": 0, "days": set(),
                                "task_start": r["task_start"], "task_end": r["task_end"]})
        g["cycle_hours"] += r["hours"]; g["rows"] += 1; g["days"].add(r["date"])
        g["hours_so_far"] = r["total_on_task"]; g["allotted_hours"] = r["allotted_hours"]; g["verdict"] = r["verdict"]
    tasks = []
    for g in by.values():
        allot, so_far = g["allotted_hours"], g["hours_so_far"]
        tasks.append({**{k: v for k, v in g.items() if k != "days"}, "days": len(g["days"]), "cycle_hours": round(g["cycle_hours"], 2),
                      "pct_used": round(100 * so_far / allot) if (allot and so_far is not None) else None,
                      "over_allotted": bool(allot and so_far is not None and so_far > allot)})
    tasks.sort(key=lambda x: (x["task_id"] is None, -x["cycle_hours"]))
    summary = {k: 0 for k in ("completed_within", "completed_over", "in_progress_within", "in_progress_over", "unplanned", "unknown")}
    for t in tasks:
        summary[t["verdict"]] += 1
    return tasks, summary


@router.get("/{cycle_id}/employee/{employee_id}")
def employee_detail(cycle_id: str, employee_id: str, current_user: str = Depends(get_current_user)):
    """Everything a reviewer needs for one employee and cycle: per date the tasks done with hours, the hours allotted to each
    task and how it stands, plus a roll-up per task. Reporting manager or admin only."""
    me = _me(current_user)
    admin = _is_admin(me)
    cyc = _configured_cycle(cycle_id)
    emp = employee_id.strip().upper()
    _authorise_all(me, [emp], admin)
    if emp not in pilot_set():
        raise HTTPException(422, f"{emp} is not on the daily timesheet")
    st = payrolls.settings()
    start, end = cyc.start.isoformat(), cyc.end.isoformat()
    subs = {x["date"]: x for x in store.submissions.find({"employee_id": emp, "date": {"$gte": start, "$lte": end}})}
    drafts = {x["date"]: x for x in store.drafts.find({"employee_id": emp, "date": {"$gte": start, "$lte": end}})}
    rows, nq_down = _review_rows(emp, cyc, st)
    hrms_by_day, typed_by_day = _hrms_and_typed(emp, cyc, st)
    by_day: dict = {}
    for r in rows:
        by_day.setdefault(r["date"], []).append(r)
    hol, today = {d.isoformat() for d in st["holidays"]}, _today()
    days, d = [], cyc.start
    while d <= cyc.end:
        iso = d.isoformat()
        day_rows = by_day.get(iso, [])
        sub = subs.get(iso)
        loc = (sub or drafts.get(iso) or {}).get("location") or (day_rows[0].get("location") if day_rows else None)
        working = d.weekday() not in st["week_off"] and iso not in hol
        days.append({
            "date": iso, "weekday": d.strftime("%a"), "working_day": working, "location": loc,
            "holiday": st["holidays"].get(d) if d in st["holidays"] else None,
            "state": "submitted" if sub else ("saved" if day_rows or iso in drafts else ("missing" if working and d <= today else "none")),
            "hours": round(sum(r["hours"] for r in day_rows if r["hours"] is not None), 2),
            "hrms": _compare_day(hrms_by_day.get(iso), *typed_by_day.get(iso, (0.0, 0)), st),
            "entries": day_rows})
        d += timedelta(days=1)
    tasks, summary = _task_rollup(rows)
    hrms_summary = {k: 0 for k in ("matched", "short", "over", "no_punch", "not_filled", "leave")}
    hrms_net = typed_on_hrms_days = 0.0
    for day in days:
        c = day["hrms"]
        if c.get("result") in hrms_summary:
            hrms_summary[c["result"]] += 1
        if c.get("kind") == "working" and c.get("net_hours") is not None:
            hrms_net += c["net_hours"]; typed_on_hrms_days += c["typed_hours"]
    hrms_summary.update({"has_data": bool(hrms_by_day), "hrms_hours": round(hrms_net, 2),
                         "typed_hours": round(typed_on_hrms_days, 2), "diff_hours": round(typed_on_hrms_days - hrms_net, 2)})
    name = (store.employees.find_one({"EmpID": emp}, {"Emp Name": 1}) or {}).get("Emp Name", "")
    review = store.reviews.find_one({"kind": "approval", "employee_id": emp, "cycle_id": cyc.id}) or {}
    row = _employee_row(emp, name, cyc, today, hol, st["week_off"], st)
    return {"cycle": {"id": cyc.id, "label": cyc.label, "start": cyc.start, "end": cyc.end, "deadline": cyc.deadline},
            "employee": row, "days": days, "tasks": tasks, "summary": summary, "hrms_summary": hrms_summary,
            "nq_unavailable": nq_down,
            "rules": {"standard_hours": st["standard_hours"], "week_off_days": list(st["week_off"]),
                      "lunch_hours": st["lunch_hours"], "tolerance_hours": st["tolerance_hours"]},
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
