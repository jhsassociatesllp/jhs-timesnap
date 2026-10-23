# backend/timesheet/team_dashboard.py
"""
Team dashboard for team leads (managers), partners and admins. Calculated when the page is opened (no nightly job).

  GET /timesheet/v2/team/options   payrolls (admin-created), the team picker for admins and partners
  GET /timesheet/v2/team/data      ?payroll=&cycle=&client=&project=&manager=   everything the page shows
  GET /timesheet/v2/team/export    the same view as an Excel file

Scope (checked on every call):
  team lead = their own reportees; admin / partner = everyone, or one manager's team with ?manager=
  anyone else gets 403.
Hours come from the NEW timesheet (timesheet_entries). Allotted hours: for each NQ task, working days between its start
and end date x hours per day (week-off days and holidays left out, admin settings), counted per assigned person.
"""
import io
import re
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

import openpyxl
import pytz
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from backend.auth import get_current_user
from backend.cycle.store import pilot_set, store
from backend.hrms import rules as hrms_rules
from backend.metrics import access
from backend.metrics.exports import XLSX, safe_cell
from backend.metrics.store import mstore
from backend.nq import repository as nq_repo
from backend.nq.models import NQUnavailable
from backend.timesheet import payrolls, rules

router = APIRouter(prefix="/timesheet/v2/team", tags=["Team dashboard"])
IST = pytz.timezone("Asia/Kolkata")
_CODE = re.compile(r"^[A-Za-z0-9_-]{2,20}$")
WATCH_PCT = 80.0               # hours used (% of allotted) at which a project with unfinished tasks goes to "Watch"
QUIET_DAYS = 14                # no hours on a project for this long while tasks are open -> "Watch"
MAX_TEAM = 1500


def _today() -> date:
    return datetime.now(IST).date()


# ─────────────────────────────── pure rules (tested) ─────────────────────────

def project_status(hours_so_far: float, allotted: Optional[float], tasks_total: int, tasks_done: int, overdue: int,
                   days_since_last: Optional[int]) -> str:
    """'late' | 'watch' | 'on_track' | 'unknown' (no task data)."""
    if tasks_total == 0 and not allotted:
        return "unknown"
    if overdue > 0 or (allotted and hours_so_far > allotted):
        return "late"
    pct_hours = 100.0 * hours_so_far / allotted if allotted else 0.0
    pct_done = 100.0 * tasks_done / tasks_total if tasks_total else 100.0
    if (allotted and pct_hours >= WATCH_PCT and pct_done < WATCH_PCT) or \
            (tasks_done < tasks_total and days_since_last is not None and days_since_last >= QUIET_DAYS):
        return "watch"
    return "on_track"


def status_reasons(hours_so_far: float, allotted: Optional[float], tasks_total: int, tasks_done: int, overdue: int,
                   days_since_last: Optional[int]) -> List[str]:
    out = []
    if overdue:
        out.append(f"{overdue} overdue task{'s' if overdue != 1 else ''}")
    if allotted and hours_so_far > allotted:
        out.append(f"{round(hours_so_far, 1)} h used, over the {round(allotted, 1)} h allotted")
    elif allotted and tasks_total and 100.0 * hours_so_far / allotted >= WATCH_PCT and 100.0 * tasks_done / tasks_total < WATCH_PCT:
        out.append(f"{round(100.0 * hours_so_far / allotted)}% of the allotted hours used but only {tasks_done} of {tasks_total} tasks done")
    if tasks_done < tasks_total and days_since_last is not None and days_since_last >= QUIET_DAYS:
        out.append(f"no hours logged for {days_since_last} days")
    return out


# ─────────────────────────────── scope ───────────────────────────────────────

def _who(current_user: str):
    me = access.me(current_user)
    firm = access.is_admin(me) or access.is_partner(me)
    reportees = [d["EmpID"].strip().upper() for d in store.employees.find({"ReportingEmpCode": me}, {"EmpID": 1}) if d.get("EmpID")]
    if not firm and not reportees:
        raise HTTPException(403, "The team dashboard is for team leads, partners and admins")
    return me, firm, reportees


def _team(me: str, firm: bool, reportees: List[str], manager: Optional[str]) -> List[str]:
    enabled = pilot_set()
    if firm:
        if manager:
            m = manager.strip().upper()
            if not _CODE.match(m):
                raise HTTPException(422, "Manager code: letters, digits, - and _ only")
            ids = [d["EmpID"].strip().upper() for d in store.employees.find({"ReportingEmpCode": m}, {"EmpID": 1}) if d.get("EmpID")]
        else:
            ids = sorted(enabled)
    else:
        ids = reportees
    team = sorted({i for i in ids if i in enabled})
    if len(team) > MAX_TEAM:
        raise HTTPException(413, "That team is too large; choose one manager's team")
    return team


def _period(payroll_id: str, cycle_id: Optional[str]):
    p = next((x for x in payrolls.list_payrolls() if x["_id"] == payroll_id), None)
    if not p:
        raise HTTPException(404, "That payroll has not been created by an admin")
    if cycle_id:
        c = next((x for x in p["cycles"] if x["id"] == cycle_id), None)
        if not c:
            raise HTTPException(404, "That cycle is not part of this payroll")
        return c["start"], c["end"], c["label"], p["label"]
    return p["start"], p["end"], "Whole payroll", p["label"]


# ─────────────────────────────── the view ────────────────────────────────────

def build_view(team: List[str], start: str, end: str, client: str, project: str) -> dict:
    st = payrolls.settings()
    today = _today()
    names = {d["EmpID"].strip().upper(): (d.get("Emp Name") or "", d.get("ReportingEmpName") or "") for d in
             store.employees.find({"EmpID": {"$in": team}}, {"EmpID": 1, "Emp Name": 1, "ReportingEmpName": 1}) if d.get("EmpID")}
    period = {"employee_id": {"$in": team}, "date": {"$gte": start, "$lte": end}, "hours": {"$ne": None}}
    flt = dict(period)
    if client:
        flt["client"] = "" if client == "__unplanned__" else client
    if project:
        flt["project_code"] = project

    facet = list(store.entries.aggregate([{"$match": flt}, {"$facet": {
        "days": [{"$group": {"_id": "$date", "h": {"$sum": "$hours"}}}, {"$sort": {"_id": 1}}],
        "projects": [{"$group": {"_id": {"c": "$client", "p": "$project_code", "n": "$project"}, "h": {"$sum": "$hours"},
                                 "people": {"$addToSet": "$employee_id"}, "unplanned": {"$sum": {"$cond": ["$is_unplanned", "$hours", 0]}}}}],
        "people": [{"$group": {"_id": "$employee_id", "h": {"$sum": "$hours"}, "days": {"$addToSet": "$date"},
                               "unplanned": {"$sum": {"$cond": ["$is_unplanned", "$hours", 0]}}}}],
        "clients": [{"$group": {"_id": "$client", "h": {"$sum": "$hours"}}}],
    }}]))
    f = facet[0] if facet else {"days": [], "projects": [], "people": [], "clients": []}

    # filter choices: whatever the team worked on in this period, ignoring the client / project filter
    choices = list(store.entries.aggregate([{"$match": period}, {"$group": {"_id": {"c": "$client", "p": "$project_code", "n": "$project"}}}]))

    # all-time hours on the projects in view (everyone who worked on them), for "hours so far"
    codes = sorted({x["_id"]["p"] for x in f["projects"] if x["_id"]["p"]})
    so_far = {x["_id"]: (x["h"], x["last"]) for x in store.entries.aggregate([
        {"$match": {"project_code": {"$in": codes}, "hours": {"$ne": None}}},
        {"$group": {"_id": "$project_code", "h": {"$sum": "$hours"}, "last": {"$max": "$date"}}}])} if codes else {}
    nq_down, nq_tasks = False, {}
    if codes:
        try:
            nq_tasks = nq_repo.get_tasks_for_projects(codes)
        except NQUnavailable:
            nq_down = True

    hol = set(st["holidays"])
    projects, tasks_total, tasks_done, overdue_total = [], 0, 0, 0
    for x in sorted(f["projects"], key=lambda r: -r["h"]):
        c, code, name = x["_id"]["c"], x["_id"]["p"], x["_id"]["n"]
        row = {"client": c or "", "project": name or "", "project_code": code or "", "hours": round(x["h"], 2),
               "people": len(x["people"]), "unplanned_hours": round(x["unplanned"], 2)}
        if not code:
            row.update({"label": "Unplanned work", "status": "unknown", "reasons": [], "hours_so_far": None, "allotted": None,
                        "tasks_total": 0, "tasks_done": 0, "overdue": 0, "last_hours": None})
        else:
            tasks = nq_tasks.get(code, [])
            allotted = sum(rules.budget_hours(t.start_date, t.end_date, hol, standard_hours=st["standard_hours"], week_off=st["week_off"])
                           * max(1, len(t.assignee_ids)) for t in tasks) if tasks else None
            done = sum(1 for t in tasks if t.is_complete)
            over = sum(1 for t in tasks if t.is_overdue and not t.is_complete)
            used, last = so_far.get(code, (0.0, None))
            quiet = (today - date.fromisoformat(last)).days if last else None
            tasks_total += len(tasks); tasks_done += done; overdue_total += over
            row.update({"label": name or code, "hours_so_far": round(used, 2), "allotted": round(allotted, 2) if allotted else None,
                        "pct_used": round(100 * used / allotted) if allotted else None, "tasks_total": len(tasks), "tasks_done": done,
                        "overdue": over, "last_hours": last,
                        "status": "unknown" if nq_down or not tasks else project_status(used, allotted, len(tasks), done, over, quiet),
                        "reasons": [] if nq_down or not tasks else status_reasons(used, allotted, len(tasks), done, over, quiet)})
        projects.append(row)

    # attendance: HRMS against typed hours, and days filled (not affected by the client / project filter)
    hrms = {}
    for h in store.hrms.find({"employee_id": {"$in": team}, "date": {"$gte": start, "$lte": end}},
                             {"employee_id": 1, "date": 1, "kind": 1, "gross_hours": 1, "leave_flag": 1}):
        hrms.setdefault(h["employee_id"], {})[h["date"]] = h
    typed_day = {}
    for x in store.entries.aggregate([{"$match": period}, {"$group": {"_id": {"e": "$employee_id", "d": "$date"}, "h": {"$sum": "$hours"}, "n": {"$sum": 1}}}]):
        typed_day[(x["_id"]["e"], x["_id"]["d"])] = (x["h"], x["n"])
    submitted = {}
    for s in store.submissions.find({"employee_id": {"$in": team}, "date": {"$gte": start, "$lte": end}}, {"employee_id": 1, "date": 1}):
        submitted.setdefault(s["employee_id"], set()).add(s["date"])

    by_person = {x["_id"]: x for x in f["people"]}
    filtered = bool(client or project)
    people, filled_sum, required_sum, hrms_total, typed_total_on_hrms = [], 0, 0, 0.0, 0.0
    d0, d1 = date.fromisoformat(start), min(date.fromisoformat(end), today)
    for emp in team:
        p = by_person.get(emp, {"h": 0.0, "days": [], "unplanned": 0.0})
        off = {d for d, h in hrms.get(emp, {}).items() if h.get("leave_flag")}
        required, d = [], d0
        while d <= d1:
            iso = d.isoformat()
            if d.weekday() not in st["week_off"] and d not in hol and iso not in off:
                required.append(iso)
            d += timedelta(days=1)
        sub = submitted.get(emp, set())
        missing = [x for x in required if x not in sub]
        h_net = diff = 0.0
        gaps = 0
        for day, h in hrms.get(emp, {}).items():
            typed, n = typed_day.get((emp, day), (0.0, 0))
            kind = h.get("kind") or hrms_rules.classify(h.get("status_code"))
            net = hrms_rules.net_from_gross(h.get("gross_hours"), st["lunch_hours"])
            res = hrms_rules.reco_result(kind, n, typed, net, st["tolerance_hours"])
            if kind == "working" and net is not None:
                h_net += net; diff += typed - net
                typed_total_on_hrms += typed
            if res in ("short", "over", "no_punch", "not_filled"):
                gaps += 1
        hrms_total += h_net
        filled_sum += len(required) - len(missing); required_sum += len(required)
        people.append({"employee_id": emp, "name": names.get(emp, ("", ""))[0], "manager": names.get(emp, ("", ""))[1],
                       "hours": round(p["h"], 2), "unplanned_hours": round(p["unplanned"], 2), "days_worked": len(p["days"]),
                       "days_filled": len(required) - len(missing), "days_required": len(required), "missing_days": len(missing),
                       "hrms_hours": None if filtered or not h_net else round(h_net, 2),
                       "diff_hours": None if filtered or not h_net else round(diff, 2), "gap_days": None if filtered else gaps})
    people.sort(key=lambda r: (-r["hours"], r["name"]))

    total_hours = round(sum(x["h"] for x in f["days"]), 2)
    unplanned_hours = round(sum(x["unplanned"] for x in f["projects"]), 2)
    clients = [{"client": x["_id"] or "Unplanned work", "hours": round(x["h"], 2),
                "share": round(100 * x["h"] / total_hours, 1) if total_hours else 0.0}
               for x in sorted(f["clients"], key=lambda r: -r["h"])]

    # a short list of what needs a look
    attention = []
    if nq_down:
        attention.append({"level": "warn", "text": "Project data from Nexus Quant is unavailable, so project status and allotted hours are not shown."})
    for pr in projects:
        if pr["status"] == "late":
            attention.append({"level": "red", "text": f"{pr['label']}: " + "; ".join(pr["reasons"])})
    for pr in projects:
        if pr["status"] == "watch":
            attention.append({"level": "amber", "text": f"{pr['label']}: " + "; ".join(pr["reasons"])})
    miss = [p for p in people if p["missing_days"]]
    if miss:
        top = ", ".join(f"{(p['name'] or p['employee_id'])} ({p['missing_days']})" for p in sorted(miss, key=lambda r: -r["missing_days"])[:4])
        attention.append({"level": "amber", "text": f"{len(miss)} {'person has' if len(miss) == 1 else 'people have'} days not submitted: {top}"})
    big = [p for p in people if (p["gap_days"] or 0) >= 3]
    if big:
        attention.append({"level": "amber", "text": f"{len(big)} {'person has' if len(big) == 1 else 'people have'} 3 or more days where typed hours differ from HRMS"})
    if total_hours and unplanned_hours / total_hours >= 0.15:
        attention.append({"level": "amber", "text": f"Unplanned work is {round(100 * unplanned_hours / total_hours)}% of the hours logged"})

    tiles = {
        "hours": total_hours, "people": len(team),
        "hrms_hours": None if filtered or not hrms_total else round(hrms_total, 2),
        "diff_hours": None if filtered or not hrms_total else round(typed_total_on_hrms - hrms_total, 2),
        "days_filled_pct": round(100 * filled_sum / required_sum) if required_sum else None,
        "tasks_total": tasks_total, "tasks_done": tasks_done, "overdue": overdue_total,
        "unplanned_pct": round(100 * unplanned_hours / total_hours) if total_hours else 0,
    }
    return {"tiles": tiles, "daily": [{"date": x["_id"], "hours": round(x["h"], 2)} for x in f["days"]], "projects": projects,
            "people": people, "clients": clients, "attention": attention, "nq_unavailable": nq_down,
            "filters": {"clients": sorted({x["_id"]["c"] or "" for x in choices}, key=lambda s: (s == "", s.lower())),
                        "projects": sorted([{"code": x["_id"]["p"], "name": x["_id"]["n"], "client": x["_id"]["c"]}
                                            for x in choices if x["_id"]["p"]], key=lambda r: (r["client"] or "", r["name"] or ""))},
            "filtered": filtered, "rules": {"week_off_days": list(st["week_off"]), "standard_hours": st["standard_hours"]}}


# ─────────────────────────────── routes ──────────────────────────────────────

@router.get("/options")
def options(current_user: str = Depends(get_current_user)):
    me, firm, reportees = _who(current_user)
    today = _today().isoformat()
    out = []
    for p in payrolls.list_payrolls():
        out.append({"id": p["_id"], "label": p["label"], "current": p["start"] <= today <= p["end"], "cycles": [
            {"id": c["id"], "label": c["label"], "current": c["start"] <= today <= c["end"]} for c in p["cycles"]]})
    managers = []
    if firm:
        for d in store.employees.aggregate([{"$match": {"ReportingEmpCode": {"$nin": ["", None]}}},
                                            {"$group": {"_id": "$ReportingEmpCode", "name": {"$first": "$ReportingEmpName"}, "n": {"$sum": 1}}},
                                            {"$sort": {"name": 1}}, {"$limit": 500}]):
            managers.append({"code": str(d["_id"]).strip().upper(), "name": d.get("name") or "", "people": d["n"]})
    return {"payrolls": out, "is_firm": firm, "managers": managers, "me": me}


def _view_for(current_user: str, payroll: str, cycle: Optional[str], client: str, project: str, manager: Optional[str]):
    me, firm, reportees = _who(current_user)
    start, end, cycle_label, payroll_label = _period(payroll, cycle)
    team = _team(me, firm, reportees, manager)
    if project and not re.match(r"^[A-Za-z0-9_.\- ]{1,40}$", project):
        raise HTTPException(422, "Bad project code")
    view = build_view(team, start, end, (client or "").strip(), (project or "").strip())
    view["period"] = {"payroll": payroll_label, "cycle": cycle_label, "start": start, "end": end}
    return me, view


@router.get("/data")
def data(payroll: str = Query(...), cycle: Optional[str] = None, client: str = "", project: str = "", manager: Optional[str] = None,
         current_user: str = Depends(get_current_user)):
    return _view_for(current_user, payroll, cycle, client, project, manager)[1]


@router.get("/export")
def export(payroll: str = Query(...), cycle: Optional[str] = None, client: str = "", project: str = "", manager: Optional[str] = None,
           current_user: str = Depends(get_current_user)):
    me, v = _view_for(current_user, payroll, cycle, client, project, manager)
    wb = openpyxl.Workbook(write_only=True)

    def sheet(title, header, rows):
        ws = wb.create_sheet(title)
        ws.append(header)
        for r in rows:
            ws.append([safe_cell(x) for x in r])

    t, pr = v["tiles"], v["period"]
    sheet("Summary", ["Item", "Value"], [
        ["Payroll", pr["payroll"]], ["Period", f"{pr['cycle']} ({pr['start']} to {pr['end']})"], ["Client filter", client or "All"],
        ["Project filter", project or "All"], ["People in view", t["people"]], ["Hours logged", t["hours"]],
        ["HRMS hours", t["hrms_hours"]], ["Typed minus HRMS", t["diff_hours"]], ["Days filled %", t["days_filled_pct"]],
        ["Tasks done", f"{t['tasks_done']} of {t['tasks_total']}"], ["Overdue tasks", t["overdue"]], ["Unplanned work %", t["unplanned_pct"]]])
    sheet("Projects", ["Client", "Project", "Code", "Status", "Hours this period", "Hours so far", "Allotted", "% used", "Tasks done",
                       "Tasks total", "Overdue", "People", "Last hours", "Why"],
          [[p["client"], p["label"], p["project_code"], p["status"], p["hours"], p["hours_so_far"], p["allotted"], p.get("pct_used"),
            p["tasks_done"], p["tasks_total"], p["overdue"], p["people"], p["last_hours"], "; ".join(p["reasons"])] for p in v["projects"]])
    sheet("People", ["Employee ID", "Name", "Manager", "Hours", "Unplanned hours", "Days worked", "Days filled", "Days required",
                     "HRMS hours", "Typed minus HRMS", "Days differing from HRMS"],
          [[p["employee_id"], p["name"], p["manager"], p["hours"], p["unplanned_hours"], p["days_worked"], p["days_filled"],
            p["days_required"], p["hrms_hours"], p["diff_hours"], p["gap_days"]] for p in v["people"]])
    sheet("Clients", ["Client", "Hours", "Share %"], [[c["client"], c["hours"], c["share"]] for c in v["clients"]])
    sheet("Hours per day", ["Date", "Hours"], [[d["date"], d["hours"]] for d in v["daily"]])
    sheet("Needs attention", ["Level", "What"], [[a["level"], a["text"]] for a in v["attention"]])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    mstore.audit.insert_one({"kind": "team-dashboard", "by": me, "from": pr["start"], "to": pr["end"], "client": client, "project": project,
                             "manager": manager or "", "rows": len(v["people"]), "at": datetime.utcnow()})
    return StreamingResponse(buf, media_type=XLSX, headers={
        "Content-Disposition": f'attachment; filename="team_dashboard_{payroll}.xlsx"', "Cache-Control": "no-store"})
