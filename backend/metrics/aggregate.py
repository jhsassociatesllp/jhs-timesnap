# backend/metrics/aggregate.py
"""
Builders for the pre-aggregated dashboard data. Everything here WRITES only the new
aggregate collections; it only READS timesheet_entries, the legacy Timesheet_data, day_submissions,
daily_reco and (through the caller) Nexus Quant.
"""
import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Dict, Iterable, List, Optional, Set, Tuple

from pymongo import UpdateOne

from backend.cycle.store import store
from backend.metrics.store import mstore
from backend.nq.models import NQTask, NQProject, NQUser
from backend.timesheet import rag, rules, scope
from backend.timesheet.legacy_migration import _entries_of

MIN_ROWS_FOR_DELETE_GUARD = 20     # below this a clean-up of stale rows is always allowed
MAX_STALE_SHARE = 0.5              # never delete more than half of what is stored in one rebuild

CAPACITY_DAYS = 10            # "team load for the next 10 days" = next 10 working days
FLAGGED_RECO = ("short", "over", "no_punch", "not_filled")
RECO_RESULTS = ("matched", "short", "over", "no_punch", "not_filled", "leave")


def ensure_indexes() -> None:
    mstore.hours.create_index([("date", 1), ("employee_id", 1), ("project_code", 1), ("source", 1)], unique=True)
    mstore.hours.create_index([("project_code", 1)])
    mstore.projects.create_index([("project_code", 1), ("date", 1)], unique=True)
    mstore.projects.create_index([("date", 1)])
    mstore.daily.create_index([("date", 1), ("manager_id", 1)], unique=True)
    mstore.team.create_index([("date", 1), ("employee_id", 1)], unique=True)


def _holidays() -> Set[str]:
    doc = store.config.find_one({"_id": "timesheet"}) or {}
    return {str(h)[:10] for h in doc.get("holidays", []) or []}


def _pilot() -> Set[str]:
    return scope.enabled_set(store.config, store.employees)


# ─────────────────────────────── hours_daily ─────────────────────────────────

def build_hours_daily(since: Optional[date] = None) -> Dict[str, int]:
    """(Re)build hours_daily for dates >= since (None = full history).
    Sources: timesheet_entries (new, excluding migrated rows) + legacy Timesheet_data.
    A legacy row is skipped when the same employee has NEW entries that day, and migrated rows
    (legacy: true) are skipped on the new side, so nothing is counted twice."""
    since_iso = since.isoformat() if since else None
    match = {"legacy": {"$ne": True}, "hours": {"$ne": None}}
    if since_iso:
        match["date"] = {"$gte": since_iso}
    acc: Dict[Tuple[str, str, str, str], dict] = {}
    new_days: Set[Tuple[str, str]] = set()

    for r in store.entries.aggregate([
            {"$match": match},
            {"$group": {"_id": {"d": "$date", "e": "$employee_id", "p": {"$ifNull": ["$project_code", ""]}},
                        "hours": {"$sum": "$hours"}, "client": {"$first": "$client"}, "project": {"$first": "$project"}}}]):
        k = (r["_id"]["d"], r["_id"]["e"], r["_id"]["p"], "new")
        acc[k] = {"hours": round(r["hours"], 2), "client": r.get("client") or "", "project": r.get("project") or ""}
        new_days.add((r["_id"]["d"], r["_id"]["e"]))

    for doc in mstore.legacy.find({}, {"employeeId": 1, "payrolls": 1}):
        emp = str(doc.get("employeeId") or "").strip().upper()
        for payroll in doc.get("payrolls", []) or []:
            for e in _entries_of(payroll):
                d = str(e.get("date") or "")[:10]
                if e.get("v2_mirror"):               # copy of an approved new-timesheet row: already counted above
                    continue
                if len(d) != 10 or (since_iso and d < since_iso) or (d, emp) in new_days:
                    continue
                try:
                    h = float(e.get("projectHours"))
                except (TypeError, ValueError):
                    continue
                if h <= 0:
                    continue
                code = str(e.get("projectCode") or "").strip().upper()
                k = (d, emp, code, "legacy")
                row = acc.setdefault(k, {"hours": 0.0, "client": str(e.get("client") or "").strip(),
                                         "project": str(e.get("project") or "").strip()})
                row["hours"] = round(row["hours"] + h, 2)

    build_id, now = uuid.uuid4().hex, datetime.utcnow()
    ops = [UpdateOne({"date": d, "employee_id": emp, "project_code": code, "source": src},
                     {"$set": {"hours": v["hours"], "client": v["client"], "project": v["project"],
                               "build_id": build_id, "updated_at": now}}, upsert=True)
           for (d, emp, code, src), v in acc.items()]
    for i in range(0, len(ops), 2000):
        mstore.hours.bulk_write(ops[i:i + 2000], ordered=False)
    scope = {"date": {"$gte": since_iso}} if since_iso else {}
    stale = {**scope, "build_id": {"$ne": build_id}}
    stale_count = mstore.hours.count_documents(stale)
    total = mstore.hours.count_documents(scope)
    # Safety valve: if the source suddenly looks (nearly) empty - wrong database, outage, bad config -
    # keep the stored data instead of wiping history. A genuine large change can be forced with --full
    # after investigating.
    if total >= MIN_ROWS_FOR_DELETE_GUARD and stale_count > MAX_STALE_SHARE * total:
        return {"rows": len(ops), "removed": 0, "delete_skipped": stale_count}
    removed = mstore.hours.delete_many(stale).deleted_count            # rows that no longer exist at the source
    return {"rows": len(ops), "removed": removed}


# ──────────────────────────────── projects ───────────────────────────────────

def _hours_by_project() -> Dict[str, dict]:
    out: Dict[str, dict] = defaultdict(lambda: {"new": 0.0, "legacy": 0.0, "last": None})
    for r in mstore.hours.aggregate([{"$group": {"_id": {"p": "$project_code", "s": "$source"},
                                                 "h": {"$sum": "$hours"}, "last": {"$max": "$date"}}}]):
        row = out[r["_id"]["p"]]
        row[r["_id"]["s"]] += r["h"]
        if r["last"] and (row["last"] is None or r["last"] > row["last"]):
            row["last"] = r["last"]
    return out


def _iso(d: Optional[date]) -> Optional[str]:
    return d.isoformat() if d else None


def compute_project_metrics(day: date, projects: List[NQProject], tasks: List[NQTask],
                            users: List[NQUser], rag_cfg: dict) -> List[dict]:
    holidays = {date.fromisoformat(h) for h in _holidays()}
    emp_of = {u.id: u.emp_id.strip().upper() for u in users}
    hours = _hours_by_project()
    by_project: Dict[int, List[NQTask]] = defaultdict(list)
    for t in tasks:
        by_project[t.project_id].append(t)
    out = []
    for p in projects:
        ts = by_project.get(p.id, [])
        budget = sum(rules.budget_hours(t.start_date, t.end_date, holidays) * len(t.assignee_ids) for t in ts)
        h = hours.get(p.project_code, {"new": 0.0, "legacy": 0.0, "last": None})
        used = round(h["new"] + h["legacy"], 2)
        done = sum(1 for t in ts if t.is_complete)
        overdue = sum(1 for t in ts if not t.is_complete and t.end_date and t.end_date < day)
        done_pct = rag.pct(done, len(ts))
        last = date.fromisoformat(h["last"]) if h["last"] else None
        stats = rag.ProjectStats(
            budget_hours=round(budget, 2), hours_used=used, tasks_total=len(ts), tasks_done=done,
            overdue_tasks=overdue, days_since_last_entry=(day - last).days if last else None,
            planned_end=p.end_date,
            forecast_end=rag.forecast_end_date(day, p.start_date, used, budget, done_pct, holidays))
        out.append({
            "date": day.isoformat(), "project_code": p.project_code, "project_name": p.project_name,
            "client_name": p.client_name,
            "manager_emp_ids": sorted({emp_of[i] for i in p.manager_ids if i in emp_of}),
            "partner_emp_id": emp_of.get(p.partner_id),
            "budget_hours": stats.budget_hours, "hours_used": used,
            "hours_new": round(h["new"], 2), "hours_legacy": round(h["legacy"], 2),
            "hours_used_pct": rag.pct(used, budget), "tasks_total": len(ts), "tasks_done": done,
            "tasks_done_pct": done_pct, "overdue_tasks": overdue,
            "days_since_last_entry": stats.days_since_last_entry,
            "planned_end": _iso(p.end_date), "forecast_end": _iso(stats.forecast_end),
            "gap_points": rag.gap_points(stats), "rag": rag.rag_status(stats, rag_cfg),
            "computed_at": datetime.utcnow()})
    return out


def save_project_metrics(day: date, docs: List[dict]) -> int:
    iso = day.isoformat()
    if docs:
        mstore.projects.bulk_write([UpdateOne({"project_code": d["project_code"], "date": iso},
                                              {"$set": d}, upsert=True) for d in docs], ordered=False)
    if docs:                      # an empty list means "NQ returned nothing": keep the last good snapshot
        mstore.projects.delete_many({"date": iso, "project_code": {"$nin": [d["project_code"] for d in docs]}})
    return len(docs)


# ─────────────────────────────── team snapshot ───────────────────────────────

def _next_working_days(day: date, n: int, holidays: Set[str]) -> List[date]:
    out, d = [], day
    while len(out) < n:
        if d.weekday() < 5 and d.isoformat() not in holidays:
            out.append(d)
        d += timedelta(days=1)
    return out


def _missing_streak(emp: str, asof: date, holidays: Set[str], submitted: Set[str], off: Set[str]) -> int:
    streak, d = 0, asof
    for _ in range(60):
        iso = d.isoformat()
        if d.weekday() < 5 and iso not in holidays and iso not in off:
            if iso in submitted:
                break
            streak += 1
        d -= timedelta(days=1)
    return streak


def compute_team_snapshot(day: date, tasks: List[NQTask], users: List[NQUser]) -> List[dict]:
    holidays = _holidays()
    window = _next_working_days(day, CAPACITY_DAYS, holidays)
    window_end = window[-1]
    capacity = round(len(window) * rules.STANDARD_HOURS, 2)
    hol_dates = {date.fromisoformat(h) for h in holidays}
    emp_of = {u.id: u.emp_id.strip().upper() for u in users}

    logged: Dict[Tuple[str, int], float] = {}
    for r in store.entries.aggregate([{"$match": {"task_id": {"$ne": None}, "hours": {"$ne": None}}},
                                      {"$group": {"_id": {"e": "$employee_id", "t": "$task_id"}, "h": {"$sum": "$hours"}}}]):
        logged[(r["_id"]["e"], r["_id"]["t"])] = r["h"]

    remaining: Dict[str, float] = defaultdict(float)
    open_tasks: Dict[str, int] = defaultdict(int)
    for t in tasks:
        if t.is_complete or not t.end_date or t.end_date > window_end:
            continue                                              # only tasks due in the window (overdue included)
        budget = rules.budget_hours(t.start_date or t.end_date, t.end_date, hol_dates)
        for uid in t.assignee_ids:
            emp = emp_of.get(uid)
            if emp:
                remaining[emp] += max(budget - logged.get((emp, t.id), 0.0), 0.0)
                open_tasks[emp] += 1

    mgr_of = {d["EmpID"].strip().upper(): (d.get("ReportingEmpCode") or "").strip().upper()
              for d in store.employees.find({}, {"EmpID": 1, "ReportingEmpCode": 1}) if d.get("EmpID")}
    pilot = _pilot()
    asof = day - timedelta(days=1)
    since = (asof - timedelta(days=90)).isoformat()
    submitted: Dict[str, Set[str]] = defaultdict(set)
    off: Dict[str, Set[str]] = defaultdict(set)
    if pilot:
        for s in store.submissions.find({"employee_id": {"$in": list(pilot)}, "date": {"$gte": since}},
                                        {"employee_id": 1, "date": 1}):
            submitted[s["employee_id"]].add(s["date"])
        for h in store.hrms.find({"employee_id": {"$in": list(pilot)}, "date": {"$gte": since}, "leave_flag": True},
                                 {"employee_id": 1, "date": 1}):
            off[h["employee_id"]].add(h["date"])

    out = []
    for emp in sorted(set(remaining) | pilot):
        rem = round(remaining.get(emp, 0.0), 2)
        out.append({
            "date": day.isoformat(), "employee_id": emp, "manager_id": mgr_of.get(emp, ""),
            "remaining_hours": rem, "capacity_hours": capacity,
            "load_pct": round(100.0 * rem / capacity, 1) if capacity else 0.0,
            "open_tasks": open_tasks.get(emp, 0), "window_end": window_end.isoformat(),
            "missing_streak": _missing_streak(emp, asof, holidays, submitted[emp], off[emp]) if emp in pilot else None,
            "is_pilot": emp in pilot})
    return out


def save_team_snapshot(day: date, docs: List[dict]) -> int:
    iso = day.isoformat()
    if docs:
        mstore.team.bulk_write([UpdateOne({"date": iso, "employee_id": d["employee_id"]}, {"$set": d}, upsert=True)
                                for d in docs], ordered=False)
    if docs:
        mstore.team.delete_many({"date": iso, "employee_id": {"$nin": [d["employee_id"] for d in docs]}})
    return len(docs)


# ──────────────────────────────── compliance ─────────────────────────────────

def compute_dashboard_daily(d: date) -> List[dict]:
    """Per manager, for one PAST working day: expected vs submitted (pilot reportees only),
    hours, unplanned/total entries and reco counts. Empty on weekends and holidays."""
    iso = d.isoformat()
    if d.weekday() >= 5 or iso in _holidays():
        return []
    pilot = _pilot()
    by_mgr: Dict[str, List[str]] = defaultdict(list)
    for e in store.employees.find({"EmpID": {"$in": list(pilot)}}, {"EmpID": 1, "ReportingEmpCode": 1}):
        mgr = (e.get("ReportingEmpCode") or "").strip().upper()
        if mgr:
            by_mgr[mgr].append(e["EmpID"].strip().upper())
    out = []
    for mgr, ids in sorted(by_mgr.items()):
        off = {h["employee_id"] for h in store.hrms.find({"employee_id": {"$in": ids}, "date": iso, "leave_flag": True},
                                                         {"employee_id": 1})}
        expected = [i for i in ids if i not in off]
        submitted = {s["employee_id"] for s in store.submissions.find({"employee_id": {"$in": expected}, "date": iso},
                                                                       {"employee_id": 1})}
        entries = list(store.entries.find({"employee_id": {"$in": ids}, "date": iso}, {"hours": 1, "is_unplanned": 1}))
        reco = {r: 0 for r in RECO_RESULTS}
        for r in store.reco.find({"employee_id": {"$in": ids}, "date": iso}, {"result": 1}):
            reco[r["result"]] = reco.get(r["result"], 0) + 1
        out.append({"date": iso, "manager_id": mgr, "team_size": len(ids), "expected": len(expected),
                    "submitted": len(submitted), "hours": round(sum(e["hours"] for e in entries if e.get("hours") is not None), 2),
                    "entries": len(entries), "unplanned": sum(1 for e in entries if e.get("is_unplanned")),
                    "reco": reco})
    return out


def save_dashboard_daily(d: date, docs: List[dict]) -> int:
    iso = d.isoformat()
    if docs:
        mstore.daily.bulk_write([UpdateOne({"date": iso, "manager_id": x["manager_id"]}, {"$set": x}, upsert=True)
                                 for x in docs], ordered=False)
    if docs:
        mstore.daily.delete_many({"date": iso, "manager_id": {"$nin": [x["manager_id"] for x in docs]}})
    return len(docs)
