# backend/metrics/admin_exports.py
"""
Data export for ADMINS: download the timesheet data as Excel or CSV from the app (no scripts needed).

  GET /admin-exports/datasets                         what can be exported (the Data export page uses this)
  GET /admin-exports/{dataset}?from=&to=&employee=&format=xlsx|csv

Datasets: entries, cycle-summary, submissions, drafts, reviews, hrms, reco, classic, export-log.
Safety: admins only (checked on every call); date range <= 366 days; optional employee filter (max 100 codes);
row cap; every cell neutralised against Excel formula injection; each export is written to export_audit.
Read-only: nothing here writes to the timesheet collections.
"""
import csv
import io
import json
import re
from datetime import date, datetime, timedelta
from typing import Dict, Iterable, Iterator, List, Optional, Tuple

import openpyxl
from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from backend.auth import get_current_user
from backend.cycle.store import store
from backend.metrics import access
from backend.metrics.exports import MAX_RANGE_DAYS, XLSX, safe_cell
from backend.metrics.store import mstore
from backend.timesheet import rules

router = APIRouter(prefix="/admin-exports", tags=["Admin exports"])
MAX_ROWS = 200_000
MAX_EMPLOYEES = 100
_CODE = re.compile(r"^[A-Za-z0-9_-]{2,20}$")

DATASETS = [
    {"id": "entries", "label": "Timesheet entries (My day)", "needs_dates": True,
     "description": "Every work row: employee, payroll, cycle, date, client, project, task, hours, status, remarks."},
    {"id": "cycle-summary", "label": "Cycle summary per employee", "needs_dates": True,
     "description": "One row per employee per 10-day cycle: payroll, days worked, hours, unplanned rows, approval status."},
    {"id": "submissions", "label": "Submitted days", "needs_dates": True,
     "description": "Which days each employee submitted, with the location and time."},
    {"id": "drafts", "label": "Saved days (not submitted)", "needs_dates": True,
     "description": "Days that were saved but not yet submitted, with their location."},
    {"id": "reviews", "label": "Manager approvals and send-backs", "needs_dates": True,
     "description": "Cycle approvals: status, who approved or sent back, the note, and the classic-copy result."},
    {"id": "hrms", "label": "HRMS attendance", "needs_dates": True,
     "description": "Attendance rows imported from the HRMS file."},
    {"id": "reco", "label": "Hours reconciliation", "needs_dates": True,
     "description": "Daily comparison of typed hours with HRMS hours, with reasons and manager reviews."},
    {"id": "classic", "label": "Classic timesheet (old format)", "needs_dates": True,
     "description": "Rows from the classic timesheet, including approved My day cycles copied there."},
    {"id": "export-log", "label": "Export log", "needs_dates": False,
     "description": "Who exported what and when (the last 5,000 exports)."},
]
_IDS = {d["id"] for d in DATASETS}


# ─────────────────────────────── helpers ───────────────────────────────────────

def _require_admin(current_user: str) -> str:
    me = access.me(current_user)
    if not access.is_admin(me):
        raise HTTPException(403, "Only admins can export data")
    return me


def _range(date_from: Optional[str], date_to: Optional[str]) -> Tuple[str, str]:
    try:
        a, b = date.fromisoformat(date_from or ""), date.fromisoformat(date_to or "")
    except ValueError:
        raise HTTPException(400, "Choose a From and To date (YYYY-MM-DD)")
    if b < a:
        raise HTTPException(400, "'To' is before 'From'")
    if (b - a).days > MAX_RANGE_DAYS:
        raise HTTPException(400, f"Range is limited to {MAX_RANGE_DAYS} days")
    return a.isoformat(), b.isoformat()


def _employees(raw: Optional[str]) -> Optional[List[str]]:
    if not raw or not raw.strip():
        return None
    codes = [c.strip().upper() for c in raw.split(",") if c.strip()]
    if len(codes) > MAX_EMPLOYEES or any(not _CODE.match(c) for c in codes):
        raise HTTPException(400, f"Employee codes: letters, digits, - or _ only, at most {MAX_EMPLOYEES}")
    return codes


def _people() -> Dict[str, Tuple[str, str]]:
    out = {}
    for d in store.employees.find({}, {"EmpID": 1, "Emp Name": 1, "ReportingEmpName": 1}):
        if d.get("EmpID"):
            out[str(d["EmpID"]).strip().upper()] = (d.get("Emp Name") or "", d.get("ReportingEmpName") or "")
    return out


def _plain(v):
    if isinstance(v, (datetime, date)):
        return v.isoformat(sep=" ", timespec="seconds") if isinstance(v, datetime) else v.isoformat()
    if isinstance(v, ObjectId):
        return str(v)
    if isinstance(v, (list, dict)):
        return json.dumps(v, default=str, ensure_ascii=False)
    return v


def _payroll(cycle_id) -> str:
    try:
        return rules.payroll_id_for_cycle(str(cycle_id))
    except (ValueError, TypeError):
        return ""


def _cycles_in(a: str, b: str) -> List[str]:
    out, d, end = [], date.fromisoformat(a), date.fromisoformat(b)
    while d <= end:
        cid = rules.cycle_for(d).id
        if cid not in out:
            out.append(cid)
        d += timedelta(days=1)
    return out


def _generic(cursor, skip=("_id",)) -> Tuple[List[str], Iterator[list]]:
    """Columns = the keys seen (first-seen order); lists/objects become JSON text."""
    docs = list(cursor)
    cols: List[str] = []
    for d in docs:
        for k in d:
            if k not in skip and k not in cols:
                cols.append(k)
    return cols, ([_plain(d.get(c)) for c in cols] for d in docs)


# ─────────────────────────────── datasets ──────────────────────────────────────

def _q(field_date: str, a: str, b: str, emps: Optional[List[str]], emp_field: str = "employee_id") -> dict:
    q = {field_date: {"$gte": a, "$lte": b}}
    if emps:
        q[emp_field] = {"$in": emps}
    return q


def ds_entries(a, b, emps):
    people = _people()
    header = ["Employee ID", "Employee name", "Reporting manager", "Payroll", "Cycle", "Date", "Location", "Client", "Project",
              "Project code", "Task", "Task status", "Hours", "What I did", "Remarks", "Unplanned work", "Approved", "Locked",
              "Source", "Saved at"]

    def rows():
        for e in store.entries.find(_q("date", a, b, emps)).sort([("employee_id", 1), ("date", 1), ("created_at", 1)]):
            name, mgr = people.get(e["employee_id"], ("", ""))
            yield [e["employee_id"], name, e.get("reporting_manager_name") or mgr, _payroll(e.get("cycle_id")), e.get("cycle_id"),
                   e.get("date"), e.get("location"), e.get("client"), e.get("project"), e.get("project_code"),
                   e.get("task_name"), e.get("task_status"), e.get("hours"), e.get("remarks"), e.get("extra_remarks"),
                   "Yes" if e.get("is_unplanned") else "", "Yes" if e.get("approved") else "", "Yes" if e.get("locked") else "",
                   "classic (migrated)" if e.get("legacy") else "My day", _plain(e.get("updated_at") or e.get("created_at"))]
    return header, rows()


def ds_cycle_summary(a, b, emps):
    people = _people()
    reviews = {(r["employee_id"], r["cycle_id"]): r for r in
               store.reviews.find({"kind": "approval", "cycle_id": {"$in": _cycles_in(a, b)}})}
    pipe = [{"$match": _q("date", a, b, emps)},
            {"$group": {"_id": {"e": "$employee_id", "c": "$cycle_id"}, "hours": {"$sum": {"$ifNull": ["$hours", 0]}},
                        "rows": {"$sum": 1}, "days": {"$addToSet": "$date"},
                        "unplanned": {"$sum": {"$cond": ["$is_unplanned", 1, 0]}}}},
            {"$sort": {"_id.e": 1, "_id.c": 1}}]
    header = ["Employee ID", "Employee name", "Reporting manager", "Payroll", "Cycle", "Days with entries", "Entries", "Hours",
              "Unplanned rows", "Status", "Approved/Sent back by", "Approved at", "Note"]

    def rows():
        for g in store.entries.aggregate(pipe):
            e, c = g["_id"]["e"], g["_id"]["c"]
            r = reviews.get((e, c), {})
            name, mgr = people.get(e, ("", ""))
            yield [e, name, mgr, _payroll(c), c, len(g["days"]), g["rows"], round(g["hours"], 2), g["unplanned"],
                   r.get("status", "pending"), r.get("approved_by") or r.get("sent_back_by") or "",
                   _plain(r.get("approved_at") or r.get("sent_back_at")), r.get("note") or ""]
    return header, rows()


def ds_submissions(a, b, emps):
    return _generic(store.submissions.find(_q("date", a, b, emps)).sort([("employee_id", 1), ("date", 1)]))


def ds_drafts(a, b, emps):
    return _generic(store.drafts.find(_q("date", a, b, emps)).sort([("employee_id", 1), ("date", 1)]))


def ds_reviews(a, b, emps):
    q = {"kind": "approval", "cycle_id": {"$in": _cycles_in(a, b)}}
    if emps:
        q["employee_id"] = {"$in": emps}
    people = _people()
    header = ["Employee ID", "Employee name", "Payroll", "Cycle", "Status", "Approved by", "Approved at", "Sent back by",
              "Sent back at", "Note", "History events", "Classic copy"]

    def rows():
        for r in store.reviews.find(q).sort([("employee_id", 1), ("cycle_id", 1)]):
            yield [r["employee_id"], people.get(r["employee_id"], ("", ""))[0], _payroll(r.get("cycle_id")), r.get("cycle_id"),
                   r.get("status"), r.get("approved_by"), _plain(r.get("approved_at")), r.get("sent_back_by"),
                   _plain(r.get("sent_back_at")), r.get("note"), len(r.get("history") or []),
                   (r.get("mirror") or {}).get("status")]
    return header, rows()


def ds_hrms(a, b, emps):
    return _generic(store.hrms.find(_q("date", a, b, emps)).sort([("employee_id", 1), ("date", 1)]))


def ds_reco(a, b, emps):
    return _generic(store.reco.find(_q("date", a, b, emps)).sort([("employee_id", 1), ("date", 1)]))


def ds_classic(a, b, emps):
    q = {"employeeId": {"$in": emps}} if emps else {}
    header = ["Employee ID", "Employee name", "Payroll cycle", "Approval status", "Date", "Work", "Client", "Project", "Project code",
              "Reporting manager entry", "Activity", "Project hours", "Remarks", "Source"]

    def rows():
        for d in store.legacy.find(q, {"employeeId": 1, "employeeName": 1, "payrolls": 1}).sort("employeeId", 1):
            for p in d.get("payrolls") or []:
                entries = p.get("entries")
                if entries is None:
                    entries = [e for w in p.get("weeks") or [] for e in w.get("entries") or []]
                for e in sorted(entries, key=lambda x: str(x.get("date") or "")):
                    day = str(e.get("date") or "")[:10]
                    if not (a <= day <= b):
                        continue
                    yield [d.get("employeeId"), d.get("employeeName"), p.get("cycle_label"), p.get("approval_status") or "",
                           day, e.get("location"), e.get("client"), e.get("project"), e.get("projectCode"),
                           e.get("reportingManagerEntry"), e.get("activity"), e.get("projectHours"), e.get("remarks"),
                           "My day (copied at approval)" if e.get("v2_mirror") else "classic"]
    return header, rows()


def ds_export_log(a, b, emps):
    return _generic(mstore.audit.find({}).sort("at", -1).limit(5000))


_BUILDERS = {"entries": ds_entries, "cycle-summary": ds_cycle_summary, "submissions": ds_submissions, "drafts": ds_drafts,
             "reviews": ds_reviews, "hrms": ds_hrms, "reco": ds_reco, "classic": ds_classic, "export-log": ds_export_log}


# ─────────────────────────────── output ────────────────────────────────────────

def _capped(rows: Iterable[list]) -> Iterator[list]:
    for n, r in enumerate(rows, start=1):
        if n > MAX_ROWS:
            raise HTTPException(413, f"More than {MAX_ROWS} rows - choose a shorter date range or fewer employees")
        yield [safe_cell(v) for v in r]


def _xlsx(sheet: str, header: List[str], rows: Iterable[list]) -> Tuple[io.BytesIO, int]:
    wb = openpyxl.Workbook(write_only=True)
    ws = wb.create_sheet(sheet[:31])
    ws.append(header)
    n = 0
    for r in _capped(rows):
        ws.append(r)
        n += 1
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf, n


def _csv(header: List[str], rows: Iterable[list]) -> Tuple[io.BytesIO, int]:
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(header)
    n = 0
    for r in _capped(rows):
        w.writerow(r)
        n += 1
    return io.BytesIO(out.getvalue().encode("utf-8-sig")), n          # BOM so Excel reads UTF-8 correctly


# ─────────────────────────────── routes ────────────────────────────────────────

@router.get("/datasets")
def datasets(current_user: str = Depends(get_current_user)):
    _require_admin(current_user)
    return {"datasets": DATASETS, "max_range_days": MAX_RANGE_DAYS, "max_rows": MAX_ROWS}


@router.get("/{dataset}")
def export(dataset: str, date_from: Optional[str] = Query(None, alias="from"), date_to: Optional[str] = Query(None, alias="to"),
           employee: Optional[str] = Query(None), format: str = Query("xlsx"), current_user: str = Depends(get_current_user)):
    me = _require_admin(current_user)
    if dataset not in _IDS:
        raise HTTPException(404, "Unknown dataset")
    if format not in ("xlsx", "csv"):
        raise HTTPException(400, "format must be xlsx or csv")
    needs_dates = next(d["needs_dates"] for d in DATASETS if d["id"] == dataset)
    a, b = _range(date_from, date_to) if needs_dates else ("", "")
    emps = _employees(employee)
    header, rows = _BUILDERS[dataset](a, b, emps)
    buf, n = _xlsx(dataset, header, rows) if format == "xlsx" else _csv(header, rows)
    mstore.audit.insert_one({"kind": f"admin-export:{dataset}", "by": me, "from": a, "to": b, "employees": emps or "all",
                             "format": format, "rows": n, "at": datetime.utcnow()})
    stamp = f"_{a}_{b}" if needs_dates else f"_{date.today().isoformat()}"
    return StreamingResponse(buf, media_type=XLSX if format == "xlsx" else "text/csv; charset=utf-8", headers={
        "Content-Disposition": f'attachment; filename="{dataset}{stamp}.{format}"', "Cache-Control": "no-store"})
