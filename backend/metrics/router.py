# backend/metrics/router.py
"""
Dashboards (wireframe screens 6 and 7). They read ONLY the pre-aggregated collections
(project_metrics, dashboard_daily, team_snapshot) - never Nexus Quant or raw timesheet entries -
so a page load is a handful of small indexed queries.

Roles (checked on every endpoint):
  /dashboard/access     any logged-in user (just reports what they may open)
  /dashboard/manager    a manager sees their OWN projects and reportees; admins and partners may pass
                        ?manager=CODE to view anyone's; everyone else gets 403
  /dashboard/portfolio  admins and partners only (firm-wide)
"""
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

import pytz
from fastapi import APIRouter, Depends, HTTPException, Query

from backend.auth import get_current_user
from backend.cycle.store import config_doc, store
from backend.metrics import access
from backend.metrics.store import mstore
from backend.timesheet import rag

router = APIRouter(prefix="/dashboard", tags=["Dashboards"])
IST = pytz.timezone("Asia/Kolkata")
RAG_ORDER = {"red": 0, "amber": 1, "green": 2}
OVERLOAD_PCT = 120.0
STREAK_ALERT = 3
RECO_BAD = ("short", "over", "no_punch", "not_filled")


def _today() -> date:
    return datetime.now(IST).date()


def _rag_cfg() -> dict:
    return {**rag.DEFAULT_RAG, **(config_doc().get("rag") or {})}


def _latest(coll) -> Optional[str]:
    doc = coll.find_one({}, {"date": 1}, sort=[("date", -1)])
    return doc["date"] if doc else None


def _names(ids) -> Dict[str, str]:
    ids = list({i for i in ids if i})
    return {d["EmpID"].strip().upper(): d.get("Emp Name", "") for d in
            store.employees.find({"EmpID": {"$in": ids}}, {"EmpID": 1, "Emp Name": 1}) if d.get("EmpID")}


def _kpis(rows: List[dict]) -> dict:
    expected = sum(r.get("expected", 0) for r in rows)
    submitted = sum(r.get("submitted", 0) for r in rows)
    entries = sum(r.get("entries", 0) for r in rows)
    unplanned = sum(r.get("unplanned", 0) for r in rows)
    reco = {k: sum((r.get("reco") or {}).get(k, 0) for r in rows)
            for k in ("matched", "short", "over", "no_punch", "not_filled", "leave")}
    judged = reco["matched"] + sum(reco[k] for k in RECO_BAD)
    pct = lambda a, b: None if not b else round(100.0 * a / b, 1)
    return {"compliance_pct": pct(submitted, expected), "unplanned_pct": pct(unplanned, entries),
            "reco_matched_pct": pct(reco["matched"], judged), "hours": round(sum(r.get("hours", 0) for r in rows), 2),
            "expected_days": expected, "submitted_days": submitted}


def _window(days: int):
    end = _today() - timedelta(days=1)
    return (end - timedelta(days=days - 1)).isoformat(), end.isoformat()


def _project_view(p: dict) -> dict:
    keep = ("project_code", "project_name", "client_name", "rag", "budget_hours", "hours_used", "hours_new",
            "hours_legacy", "hours_used_pct", "tasks_total", "tasks_done", "tasks_done_pct", "overdue_tasks",
            "days_since_last_entry", "planned_end", "forecast_end", "gap_points", "manager_emp_ids", "partner_emp_id")
    return {k: p.get(k) for k in keep}


def _sort_worst_first(projects: List[dict]) -> List[dict]:
    return sorted(projects, key=lambda p: (RAG_ORDER.get(p["rag"], 3), -(p.get("overdue_tasks") or 0),
                                           -(p.get("gap_points") or 0), p["project_code"]))


def _project_alerts(projects: List[dict], cfg: dict) -> List[dict]:
    out = []
    for p in projects:
        label = f"{p['project_code']} {p.get('project_name') or ''}".strip()
        if p["rag"] == "red":
            why = []
            if p.get("overdue_tasks"):
                why.append(f"{p['overdue_tasks']} overdue task(s)")
            if (p.get("gap_points") or 0) > cfg["red_gap_pts"]:
                why.append(f"hours used {p['gap_points']} pts ahead of tasks done")
            out.append({"level": "red", "text": f"{label} is red" + (": " + ", ".join(why) if why else "")})
        idle = p.get("days_since_last_entry")
        if idle is not None and idle >= cfg["amber_idle_days"]:
            out.append({"level": "amber", "text": f"{label}: no hours logged for {idle} days"})
    return out


# ─────────────────────────────── routes ──────────────────────────────────────

@router.get("/access")
def my_access(current_user: str = Depends(get_current_user)):
    admin, partner, manager = access.is_admin(current_user), access.is_partner(current_user), access.is_manager(current_user)
    return {"is_admin": admin, "is_partner": partner, "is_manager": manager,
            "manager_dashboard": manager or admin or partner, "portfolio": admin or partner}


@router.get("/manager")
def manager_dashboard(manager: Optional[str] = None, days: int = Query(10, ge=1, le=90),
                      current_user: str = Depends(get_current_user)):
    me = access.me(current_user)
    firm = access.can_see_firm(me)
    target = access.me(manager) if manager else me
    if target != me and not firm:
        raise HTTPException(403, "You can only view your own dashboard")
    if target == me and not (access.is_manager(me) or firm):
        raise HTTPException(403, "Only managers, partners and admins have a dashboard")

    cfg = _rag_cfg()
    as_of = _latest(mstore.projects)
    projects = [_project_view(p) for p in mstore.projects.find({"date": as_of, "manager_emp_ids": target})] if as_of else []
    projects = _sort_worst_first(projects)

    start, end = _window(days)
    daily = list(mstore.daily.find({"manager_id": target, "date": {"$gte": start, "$lte": end}}))
    team_date = _latest(mstore.team)
    team = list(mstore.team.find({"date": team_date, "manager_id": target})) if team_date else []
    names = _names([t["employee_id"] for t in team] + [e for p in projects for e in p["manager_emp_ids"]])
    load = sorted(({"employee_id": t["employee_id"], "employee_name": names.get(t["employee_id"], ""),
                    "load_pct": t["load_pct"], "remaining_hours": t["remaining_hours"],
                    "capacity_hours": t["capacity_hours"], "open_tasks": t["open_tasks"],
                    "window_end": t["window_end"]} for t in team), key=lambda r: -r["load_pct"])

    alerts = _project_alerts(projects, cfg)
    for t in team:
        nm = names.get(t["employee_id"]) or t["employee_id"]
        if (t.get("missing_streak") or 0) >= STREAK_ALERT:
            alerts.append({"level": "amber", "text": f"{nm} has not submitted for {t['missing_streak']} working days"})
        if t["load_pct"] > OVERLOAD_PCT:
            alerts.append({"level": "amber", "text": f"{nm} is at {t['load_pct']}% load over the next 10 working days"})
    return {
        "manager": target, "as_of": as_of, "window": {"from": start, "to": end},
        "kpis": {"active_projects": len(projects), "overdue_tasks": sum(p["overdue_tasks"] or 0 for p in projects),
                 **_kpis(daily)},
        "projects": projects, "team_load": load, "alerts": alerts,
        "notes": {"hours_include_legacy": True, "compliance_pilot_only": True, "allocation_assumed_100": True},
    }


@router.get("/portfolio")
def portfolio(days: int = Query(10, ge=1, le=90), current_user: str = Depends(get_current_user)):
    if not access.can_see_firm(current_user):
        raise HTTPException(403, "Only partners and admins can view the portfolio")
    cfg = _rag_cfg()
    as_of = _latest(mstore.projects)
    projects = [_project_view(p) for p in mstore.projects.find({"date": as_of})] if as_of else []
    start, end = _window(days)
    daily = list(mstore.daily.find({"date": {"$gte": start, "$lte": end}}))

    counts = {"red": 0, "amber": 0, "green": 0}
    for p in projects:
        counts[p["rag"]] = counts.get(p["rag"], 0) + 1
    names = _names([m for p in projects for m in p["manager_emp_ids"]] + [d["manager_id"] for d in daily])
    at_risk = []
    for p in _sort_worst_first(projects):
        late = None
        if p.get("forecast_end") and p.get("planned_end"):
            late = (date.fromisoformat(p["forecast_end"]) - date.fromisoformat(p["planned_end"])).days
        if p["rag"] != "green":
            at_risk.append({**p, "days_late_forecast": late,
                            "manager_names": [names.get(m, m) for m in p["manager_emp_ids"]]})
    by_mgr: Dict[str, List[dict]] = {}
    for d in daily:
        by_mgr.setdefault(d["manager_id"], []).append(d)
    compliance = sorted(({"manager_id": m, "manager_name": names.get(m, ""), "team_size": max(r["team_size"] for r in rows),
                          **_kpis(rows)} for m, rows in by_mgr.items()),
                        key=lambda r: (r["compliance_pct"] is None, r["compliance_pct"] or 0))
    return {
        "as_of": as_of, "window": {"from": start, "to": end},
        "kpis": {"projects": len(projects), "red": counts["red"], "amber": counts["amber"], "green": counts["green"],
                 "overdue_tasks": sum(p["overdue_tasks"] or 0 for p in projects),
                 "hours_used": round(sum(p["hours_used"] or 0 for p in projects), 2), **_kpis(daily)},
        "at_risk_projects": at_risk, "alerts": _project_alerts(projects, cfg)[:50],
        "compliance_by_manager": compliance,
        "notes": {"hours_include_legacy": True, "compliance_pilot_only": True, "allocation_assumed_100": True},
    }
