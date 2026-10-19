# backend/metrics/exports.py
"""
Excel exports for partners and admins only (firm-wide data). Built from the pre-aggregated
hours_daily collection, so they are cheap and include legacy + new timesheet hours (split by source).

  GET /exports/project-hours?from=&to=       project x employee hours
  GET /exports/client-allocation?from=&to=   employee x client hours per payroll cycle (+ % of employee total)
  GET /exports/employee-projects?from=&to=   each employee's projects with hours and first/last/days worked

Safety: range <= 366 days, row cap, every cell neutralised against Excel formula injection
(= + - @ at the start), and each export is written to export_audit.
"""
import io
from collections import defaultdict
from datetime import date, datetime
from typing import Dict, List, Tuple

import openpyxl
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from backend.auth import get_current_user
from backend.cycle.store import store
from backend.metrics import access
from backend.metrics.store import mstore

router = APIRouter(prefix="/exports", tags=["Exports"])
MAX_RANGE_DAYS = 366
MAX_ROWS = 50_000
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_DANGEROUS = ("=", "+", "-", "@", "\t", "\r")


def safe_cell(v):
    """Strings that Excel could evaluate as a formula get a leading apostrophe; control chars are dropped."""
    if isinstance(v, str):
        v = "".join(ch for ch in v if ch == "\t" or ch >= " ")
        if v.startswith(_DANGEROUS):
            return "'" + v
    return v


def _require_firm(current_user: str) -> str:
    me = access.me(current_user)
    if not access.can_see_firm(me):
        raise HTTPException(403, "Only partners and admins can export firm-wide data")
    return me


def _range(date_from: str, date_to: str) -> Tuple[str, str]:
    try:
        a, b = date.fromisoformat(date_from), date.fromisoformat(date_to)
    except ValueError:
        raise HTTPException(400, "from/to must be YYYY-MM-DD")
    if b < a:
        raise HTTPException(400, "'to' is before 'from'")
    if (b - a).days > MAX_RANGE_DAYS:
        raise HTTPException(400, f"Range is limited to {MAX_RANGE_DAYS} days")
    return a.isoformat(), b.isoformat()


def _names(ids) -> Dict[str, str]:
    return {d["EmpID"].strip().upper(): d.get("Emp Name", "") for d in
            store.employees.find({"EmpID": {"$in": list(set(ids))}}, {"EmpID": 1, "Emp Name": 1}) if d.get("EmpID")}


def _xlsx_response(kind: str, me: str, a: str, b: str, sheet: str, header: List[str], rows: List[list]) -> StreamingResponse:
    if len(rows) > MAX_ROWS:
        raise HTTPException(413, f"More than {MAX_ROWS} rows - choose a shorter date range")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet
    ws.append(header)
    for r in rows:
        ws.append([safe_cell(v) for v in r])
    ws.freeze_panes = "A2"
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    mstore.audit.insert_one({"kind": kind, "by": me, "from": a, "to": b, "rows": len(rows), "at": datetime.utcnow()})
    return StreamingResponse(buf, media_type=XLSX, headers={
        "Content-Disposition": f'attachment; filename="{kind}_{a}_{b}.xlsx"', "Cache-Control": "no-store"})


@router.get("/project-hours")
def project_hours(date_from: str = Query(..., alias="from"), date_to: str = Query(..., alias="to"),
                  current_user: str = Depends(get_current_user)):
    me = _require_firm(current_user)
    a, b = _range(date_from, date_to)
    acc: Dict[Tuple[str, str], dict] = {}
    for r in mstore.hours.find({"date": {"$gte": a, "$lte": b}}):
        row = acc.setdefault((r["project_code"], r["employee_id"]),
                             {"project": r.get("project", ""), "client": r.get("client", ""), "new": 0.0, "legacy": 0.0})
        row[r["source"]] += r["hours"]
    names = _names(k[1] for k in acc)
    rows = [[code or "(none)", v["project"], v["client"], emp, names.get(emp, ""), round(v["new"] + v["legacy"], 2),
             round(v["new"], 2), round(v["legacy"], 2)] for (code, emp), v in sorted(acc.items())]
    return _xlsx_response("project-hours", me, a, b, "Project hours",
                          ["Project code", "Project", "Client", "Employee ID", "Employee name", "Hours",
                           "Hours (new timesheet)", "Hours (legacy timesheet)"], rows)


@router.get("/client-allocation")
def client_allocation(date_from: str = Query(..., alias="from"), date_to: str = Query(..., alias="to"),
                      current_user: str = Depends(get_current_user)):
    """Hours per employee per client inside each legacy PAYROLL cycle (e.g. 21st-20th) that overlaps the
    range (hours are clipped to the range), with each client's % of the employee's cycle total."""
    me = _require_firm(current_user)
    a, b = _range(date_from, date_to)
    cycles = [c for c in mstore.payroll_cycles.find({}) if c.get("start_date") and c.get("end_date")
              and str(c["end_date"])[:10] >= a and str(c["start_date"])[:10] <= b]
    if not cycles:
        raise HTTPException(422, "No payroll cycle overlaps that date range")
    cycles.sort(key=lambda c: str(c["start_date"]))
    names_needed, rows = [], []
    for c in cycles:
        lo, hi = max(a, str(c["start_date"])[:10]), min(b, str(c["end_date"])[:10])
        per: Dict[Tuple[str, str], float] = defaultdict(float)
        for r in mstore.hours.find({"date": {"$gte": lo, "$lte": hi}}):
            per[(r["employee_id"], r.get("client") or "(no client)")] += r["hours"]
        totals: Dict[str, float] = defaultdict(float)
        for (emp, _), h in per.items():
            totals[emp] += h
        for (emp, client), h in sorted(per.items()):
            names_needed.append(emp)
            rows.append([c.get("cycle_label", ""), lo, hi, emp, None, client, round(h, 2),
                         round(100.0 * h / totals[emp], 1) if totals[emp] else 0.0])
    names = _names(names_needed)
    for r in rows:
        r[4] = names.get(r[3], "")
    return _xlsx_response("client-allocation", me, a, b, "Client allocation",
                          ["Payroll cycle", "From", "To", "Employee ID", "Employee name", "Client", "Hours",
                           "% of employee hours"], rows)


@router.get("/employee-projects")
def employee_projects(date_from: str = Query(..., alias="from"), date_to: str = Query(..., alias="to"),
                      current_user: str = Depends(get_current_user)):
    me = _require_firm(current_user)
    a, b = _range(date_from, date_to)
    acc: Dict[Tuple[str, str], dict] = {}
    for r in mstore.hours.find({"date": {"$gte": a, "$lte": b}}):
        row = acc.setdefault((r["employee_id"], r["project_code"]), {
            "project": r.get("project", ""), "client": r.get("client", ""), "hours": 0.0, "days": set(),
            "first": r["date"], "last": r["date"]})
        row["hours"] += r["hours"]
        row["days"].add(r["date"])
        row["first"], row["last"] = min(row["first"], r["date"]), max(row["last"], r["date"])
    names = _names(k[0] for k in acc)
    rows = [[emp, names.get(emp, ""), code or "(none)", v["project"], v["client"], round(v["hours"], 2),
             v["first"], v["last"], len(v["days"])] for (emp, code), v in sorted(acc.items())]
    return _xlsx_response("employee-projects", me, a, b, "Employee projects",
                          ["Employee ID", "Employee name", "Project code", "Project", "Client", "Hours",
                           "First date", "Last date", "Days worked"], rows)
