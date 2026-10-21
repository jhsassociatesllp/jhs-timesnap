# backend/cycle/mirror.py
"""
Copies an APPROVED 10-day cycle of the new timesheet into the classic Timesheet_data, so the old reports,
exports and approval lists keep working.

  * Classic payrolls run 21st -> 20th; every 10-day cycle falls inside exactly one of them. The cycle's rows
    are MERGED into that payroll: only rows this module wrote (v2_mirror = true, v2_cycle_id = the cycle) are
    replaced, every other row is left alone. Running it twice gives the same result.
  * Rows carry v2_mirror = true so the dashboards (backend.metrics.aggregate) do not count the hours twice.
  * The payroll's approval_status becomes "approved" only when ALL 10-day cycles inside it are approved.
  * Nothing in Timesheet_data is deleted except the mirrored rows of the cycle being re-written or unlocked.
"""
from datetime import date, datetime, timedelta
from typing import List, Optional

from backend.cycle.store import store
from backend.timesheet import rules


def _payroll_cycle_for(cyc: rules.Cycle) -> Optional[dict]:
    """The classic payroll cycle that contains the whole 10-day cycle (by start/end date), or None."""
    s, e = cyc.start.isoformat(), cyc.end.isoformat()
    for doc in store.payroll_cycles.find({}):
        if str(doc.get("start_date") or "")[:10] <= s and str(doc.get("end_date") or "")[:10] >= e:
            return doc
    return None


def _subcycles_of(payroll_doc: dict) -> List[rules.Cycle]:
    d = date.fromisoformat(str(payroll_doc["start_date"])[:10])
    end = date.fromisoformat(str(payroll_doc["end_date"])[:10])
    out = {}
    while d <= end:
        c = rules.cycle_for(d)
        out[c.id] = c
        d += timedelta(days=1)
    return list(out.values())


def _legacy_rows(emp: str, cyc: rules.Cycle) -> List[dict]:
    rows, entry_days = [], set()
    for e in store.entries.find({"employee_id": emp, "cycle_id": cyc.id, "legacy": {"$ne": True}}).sort(
            [("date", 1), ("created_at", 1)]):
        entry_days.add(e["date"])
        unplanned = bool(e.get("is_unplanned"))
        rows.append({
            "id": f"v2_{e['_id']}", "date": e["date"], "location": e.get("location") or "",
            "projectStartTime": "", "projectEndTime": "", "lunchTime": "", "travelTime": "", "billable": "",
            "client": e.get("client") or "", "project": e.get("project") or "",
            "projectCode": e.get("project_code") or "",
            "reportingManagerEntry": e.get("reporting_manager_name") or "",
            "activity": e.get("task_name") or ("Unplanned work" if unplanned else ""),
            "projectHours": "" if e.get("hours") is None else str(e["hours"]),
            "remarks": e.get("remarks") or "",
            "nqTaskId": e.get("task_id"), "activityOther": unplanned,
            "activityReason": (e.get("remarks") or "") if unplanned else "",
            "v2_mirror": True, "v2_cycle_id": cyc.id,
        })
    for s in store.submissions.find({"employee_id": emp, "cycle_id": cyc.id, "legacy": {"$ne": True}}):
        if s["date"] not in entry_days and s.get("location") in rules.DAY_OFF_LOCATIONS:
            rows.append({"id": f"v2_off_{emp}_{s['date']}", "date": s["date"], "location": s["location"],
                         "projectStartTime": "", "projectEndTime": "", "lunchTime": "", "travelTime": "",
                         "billable": "", "client": "", "project": "", "projectCode": "", "reportingManagerEntry": "",
                         "activity": "", "projectHours": "", "remarks": "",
                         "v2_mirror": True, "v2_cycle_id": cyc.id})
    rows.sort(key=lambda r: r["date"])
    return rows


def _total(entries: List[dict]) -> float:
    total = 0.0
    for e in entries:
        try:
            total += float(e.get("projectHours") or 0)
        except (TypeError, ValueError):
            pass
    return round(total, 2)


def _meta_of(emp: str) -> dict:
    d = store.employees.find_one({"EmpID": emp}) or {}
    return {"employeeName": d.get("Emp Name", ""), "designation": d.get("Designation Name", ""),
            "gender": d.get("Gender", ""), "partner": d.get("Partner", ""),
            "reportingManager": d.get("ReportingEmpName", "")}


def _all_approved(emp: str, payroll_doc: dict) -> bool:
    ids = [c.id for c in _subcycles_of(payroll_doc)]
    done = store.reviews.count_documents({"kind": "approval", "employee_id": emp, "cycle_id": {"$in": ids},
                                          "status": "approved"})
    return done == len(ids)


def _set_lists(emp: str, approved: bool) -> None:
    """Classic Pending/Approved/Rejected lists (one doc per reporting manager)."""
    d = store.employees.find_one({"EmpID": emp}, {"ReportingEmpCode": 1, "ReportingEmpName": 1}) or {}
    mgr = (d.get("ReportingEmpCode") or "").strip().upper()
    if not mgr:
        return
    store.pending.update_one({"ReportingEmpCode": mgr}, {"$pull": {"EmployeesCodes": emp}})
    store.rejected.update_one({"ReportingEmpCode": mgr}, {"$pull": {"EmployeesCodes": emp}})
    if approved:
        store.approved.update_one(
            {"ReportingEmpCode": mgr},
            {"$addToSet": {"EmployeesCodes": emp},
             "$setOnInsert": {"ReportingEmpName": d.get("ReportingEmpName", ""),
                              "created_time": datetime.utcnow().isoformat()}}, upsert=True)
    else:
        store.approved.update_one({"ReportingEmpCode": mgr}, {"$pull": {"EmployeesCodes": emp}})


def write(emp: str, cyc: rules.Cycle, approver: str, approver_name: str = "") -> dict:
    """Mirror one approved cycle. Returns {"status": "ok" | "no_payroll_cycle" | "legacy_shape", ...}."""
    emp = emp.strip().upper()
    pdoc = _payroll_cycle_for(cyc)
    if not pdoc:
        return {"status": "no_payroll_cycle", "rows": 0}
    pid = str(pdoc["_id"])
    new_rows = _legacy_rows(emp, cyc)
    now_iso = datetime.utcnow().isoformat()
    doc = store.legacy.find_one({"employeeId": emp})
    payrolls = (doc or {}).get("payrolls", []) or []
    payroll = next((p for p in payrolls if p.get("cycle_id") == pid), None)
    if payroll is None:
        payroll = {"cycle_id": pid, "cycle_label": pdoc.get("cycle_label", ""), "submitted": True,
                   "submitted_at": now_iso, "metadata": {}, "entries": []}
        payrolls.append(payroll)
    if "entries" not in payroll:                    # oldest document shape: never reshape it
        return {"status": "legacy_shape", "rows": 0}
    payroll["entries"] = [e for e in payroll.get("entries") or []
                          if not (e.get("v2_mirror") and e.get("v2_cycle_id") == cyc.id)] + new_rows
    payroll["totalHours"] = _total(payroll["entries"])
    payroll["submitted"] = True
    payroll["submitted_at"] = payroll.get("submitted_at") or now_iso
    complete = _all_approved(emp, pdoc)
    if complete:
        payroll.update({"approval_status": "approved", "approved_by": approver, "approved_by_name": approver_name,
                        "approved_at": now_iso, "status_updated_at": now_iso})
    else:
        payroll["approval_status"] = None
    if doc:
        store.legacy.update_one({"employeeId": emp}, {"$set": {"payrolls": payrolls, "updated_time": now_iso}})
    else:
        store.legacy.insert_one({**_meta_of(emp), "employeeId": emp, "payrolls": payrolls,
                                 "created_time": now_iso, "updated_time": now_iso})
    if complete:
        _set_lists(emp, approved=True)
        store.approval_history.insert_one({
            "employeeId": emp, "employeeName": _meta_of(emp)["employeeName"], "cycle_id": pid,
            "cycle_label": pdoc.get("cycle_label", ""), "action": "approved", "actor_code": approver,
            "actor_name": approver_name, "entries": payroll["entries"], "reason": "", "timestamp": now_iso})
    return {"status": "ok", "rows": len(new_rows), "payroll_approved": complete, "payroll_cycle_id": pid}


def remove(emp: str, cyc: rules.Cycle) -> dict:
    """Undo the mirror of one cycle (admin unlock): drop its mirrored rows and the payroll's approved flag."""
    emp = emp.strip().upper()
    pdoc = _payroll_cycle_for(cyc)
    doc = store.legacy.find_one({"employeeId": emp})
    if not pdoc or not doc:
        return {"status": "nothing_to_do"}
    pid, payrolls, changed = str(pdoc["_id"]), doc.get("payrolls", []) or [], False
    for p in payrolls:
        if p.get("cycle_id") == pid and "entries" in p:
            p["entries"] = [e for e in p["entries"] if not (e.get("v2_mirror") and e.get("v2_cycle_id") == cyc.id)]
            p["totalHours"] = _total(p["entries"])
            p["approval_status"] = None
            for k in ("approved_by", "approved_by_name", "approved_at"):
                p.pop(k, None)
            changed = True
    if changed:
        store.legacy.update_one({"employeeId": emp}, {"$set": {"payrolls": payrolls,
                                                              "updated_time": datetime.utcnow().isoformat()}})
        _set_lists(emp, approved=False)
    return {"status": "ok" if changed else "nothing_to_do"}
