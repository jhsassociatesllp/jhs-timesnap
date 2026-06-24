# backend/timesheet/router.py
"""
New unified document structure (one doc per employee):
{
  "employeeId": "JHS001",
  "employeeName": "...", "designation": "...", "gender": "...",
  "partner": "...", "reportingManager": "...",
  "payrolls": [
    {
      "cycle_id": "abc123",
      "cycle_label": "Apr-May 2026",
      "submitted": false,
      "submitted_at": null,
      "metadata": { "hits": "", "misses": "", "feedback_hr": "", ... },
      "weeks": [
        {
          "week_period": "21/04/2026 to 26/04/2026",
          "entries": [ { "id": "...", "date": "...", ... } ]
        }
      ]
    }
  ],
  "updated_time": "...",
  "created_time": "..."
}
"""
import hashlib
import json
from datetime import datetime
from typing import List, Optional

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, status, Body

from backend.database import (
    timesheets_collection,
    timesheet_temp_collection,
    employee_details_collection,
    client_details_collection,
    pending_collection,
    approved_collection,
    rejected_collection,
    reporting_managers_collection,
    db,
)
from backend.auth import get_current_user
from backend.timesheet.models import (
    TimesheetEntry,
    UpdateTimesheetRequest,
    ApproveAllRequest,
)

router = APIRouter(prefix="/timesheet", tags=["Timesheet"])


# ─────────────────────────── helpers ────────────────────────────────────────

def compute_entry_hash(entry: dict) -> str:
    key = {k: entry.get(k, "") for k in [
        "date", "location", "projectStartTime", "projectEndTime",
        "client", "project", "projectCode", "reportingManagerEntry",
        "activity", "projectHours", "billable", "remarks",
        "lunchTime", "travelTime",
    ]}
    return hashlib.sha256(json.dumps(key, sort_keys=True).encode()).hexdigest()


def add_or_create(collection, reporting_emp_code: str, reporting_emp_name: str, employee_code: str):
    existing = collection.find_one({"ReportingEmpCode": reporting_emp_code})
    if existing:
        if employee_code not in existing.get("EmployeesCodes", []):
            collection.update_one(
                {"ReportingEmpCode": reporting_emp_code},
                {"$addToSet": {"EmployeesCodes": employee_code}},
            )
    else:
        collection.insert_one({
            "ReportingEmpCode": reporting_emp_code,
            "ReportingEmpName": reporting_emp_name,
            "EmployeesCodes": [employee_code],
            "created_time": datetime.utcnow().isoformat(),
        })


def recalc_totals_from_payrolls(payrolls: list) -> tuple:
    """Recalc totals for the entire document (sum of all payrolls)."""
    total = billable = non_billable = 0.0
    for payroll in payrolls:
        for week in payroll.get("weeks", []):
            for e in week.get("entries", []):
                try:
                    hrs = float(e.get("projectHours", 0))
                except (ValueError, TypeError):
                    hrs = 0.0
                total += hrs
                if e.get("billable") == "Yes":
                    billable += hrs
                elif e.get("billable") == "No":
                    non_billable += hrs
    return round(total, 2), round(billable, 2), round(non_billable, 2)


def recalc_payroll_totals(payroll: dict) -> tuple:
    """Recalc totals for a single payroll."""
    total = billable = non_billable = 0.0
    for week in payroll.get("weeks", []):
        for e in week.get("entries", []):
            try:
                hrs = float(e.get("projectHours", 0))
            except (ValueError, TypeError):
                hrs = 0.0
            total += hrs
            if e.get("billable") == "Yes":
                billable += hrs
            elif e.get("billable") == "No":
                non_billable += hrs
    return round(total, 2), round(billable, 2), round(non_billable, 2)


def _get_or_create_payroll(payrolls: list, cycle_id: str, cycle_label: str) -> dict:
    """Find existing payroll entry or create a new one."""
    for p in payrolls:
        if p.get("cycle_id") == cycle_id:
            return p
    new_payroll = {
        "cycle_id": cycle_id,
        "cycle_label": cycle_label,
        "submitted": False,
        "submitted_at": None,
        "metadata": {},
        "weeks": [],
    }
    payrolls.append(new_payroll)
    return new_payroll


def _upsert_week(payroll: dict, week_period: str, entries: list):
    """Replace or add a week's entries in a payroll."""
    for w in payroll["weeks"]:
        if w["week_period"] == week_period:
            w["entries"] = entries
            return
    payroll["weeks"].append({"week_period": week_period, "entries": entries})


# ───────────────────────────── routes ────────────────────────────────────────

@router.post("/save-draft")
async def save_draft(
    cycle_id: str = Body(...),
    cycle_label: str = Body(...),
    week_period: str = Body(...),
    entries: list = Body(...),
    metadata: dict = Body(default={}),
    current_user: str = Depends(get_current_user),
):
    """Save one week's entries as draft (Timesheet_temp). New unified structure."""
    now_iso = datetime.utcnow().isoformat()

    # Validate lunch time if required by this cycle
    from backend.database import payroll_cycles_collection
    show_lunch_travel = True
    try:
        cycle_doc = payroll_cycles_collection.find_one({"_id": ObjectId(cycle_id)})
        if cycle_doc:
            show_lunch_travel = cycle_doc.get("show_lunch_travel", True)
    except Exception:
        pass

    if show_lunch_travel:
        lunch_errors = []
        for i, entry in enumerate(entries):
            lt = entry.get("lunchTime", "") or ""
            if not lt.strip():
                lunch_errors.append(f"Row {i + 1}: Lunch Time is required")
        if lunch_errors:
            raise HTTPException(400, "; ".join(lunch_errors[:5]))

    # Assign IDs to entries
    new_entries = []
    for e in entries:
        entry = dict(e)
        entry["id"] = entry.get("id") or str(ObjectId())
        entry.setdefault("created_time", now_iso)
        entry["updated_time"] = now_iso
        new_entries.append(entry)

    doc = timesheet_temp_collection.find_one({"employeeId": current_user})

    if doc:
        payrolls = doc.get("payrolls", [])
        payroll = _get_or_create_payroll(payrolls, cycle_id, cycle_label)
        _upsert_week(payroll, week_period, new_entries)
        if metadata:
            payroll["metadata"] = metadata
        timesheet_temp_collection.update_one(
            {"employeeId": current_user},
            {"$set": {"payrolls": payrolls, "updated_time": now_iso}}
        )
    else:
        payroll = {
            "cycle_id": cycle_id,
            "cycle_label": cycle_label,
            "submitted": False,
            "submitted_at": None,
            "metadata": metadata or {},
            "weeks": [{"week_period": week_period, "entries": new_entries}],
        }
        timesheet_temp_collection.insert_one({
            "employeeId": current_user,
            "payrolls": [payroll],
            "created_time": now_iso,
            "updated_time": now_iso,
        })

    return {"success": True, "message": f"Week '{week_period}' saved as draft"}


@router.get("/draft/{employee_id}")
async def get_draft(
    employee_id: str,
    cycle_id: str,
    current_user: str = Depends(get_current_user),
):
    """Get draft for a specific cycle."""
    if employee_id.upper() != current_user.upper():
        raise HTTPException(403, "Unauthorized")

    doc = timesheet_temp_collection.find_one({"employeeId": current_user})
    if not doc:
        return {"draft": None, "submitted": False}

    doc["_id"] = str(doc["_id"])
    # Find the specific payroll
    for p in doc.get("payrolls", []):
        if p.get("cycle_id") == cycle_id:
            return {"draft": p, "submitted": p.get("submitted", False)}

    return {"draft": None, "submitted": False}


@router.get("/submission-status/{employee_id}")
async def get_submission_status(
    employee_id: str,
    current_user: str = Depends(get_current_user),
):
    """Returns submission status for all cycles."""
    if employee_id.upper() != current_user.upper():
        raise HTTPException(403, "Unauthorized")

    doc = timesheet_temp_collection.find_one({"employeeId": current_user})
    if not doc:
        return {"status": {}}

    result = {}
    for p in doc.get("payrolls", []):
        cid = p.get("cycle_id", "")
        result[cid] = {
            "submitted": p.get("submitted", False),
            "cycle_label": p.get("cycle_label", ""),
            "updated_time": doc.get("updated_time", ""),
        }
    return {"status": result}


@router.post("/submit")
async def submit_timesheet(
    cycle_id: str = Body(...),
    cycle_label: str = Body(...),
    metadata: dict = Body(default={}),
    current_user: str = Depends(get_current_user),
):
    """Submit: move draft payroll → main Timesheet_data. Mark as submitted."""
    now_iso = datetime.utcnow().isoformat()

    temp_doc = timesheet_temp_collection.find_one({"employeeId": current_user})
    if not temp_doc:
        raise HTTPException(404, "No draft found")

    # Find the payroll in temp
    temp_payroll = None
    for p in temp_doc.get("payrolls", []):
        if p.get("cycle_id") == cycle_id:
            temp_payroll = p
            break
    if not temp_payroll:
        raise HTTPException(404, "No draft found for this cycle")

    emp_id = current_user
    meta = temp_payroll.get("metadata") or metadata or {}

    # Build entries with dedup
    existing_doc = timesheets_collection.find_one({"employeeId": emp_id})
    existing_payrolls = existing_doc.get("payrolls", []) if existing_doc else []

    # Find or create payroll in main collection
    main_payroll = None
    for p in existing_payrolls:
        if p.get("cycle_id") == cycle_id:
            main_payroll = p
            break
    if not main_payroll:
        main_payroll = {
            "cycle_id": cycle_id,
            "cycle_label": cycle_label,
            "submitted": False,
            "submitted_at": None,
            "metadata": meta,
            "weeks": [],
        }
        existing_payrolls.append(main_payroll)

    # Collect existing hashes
    existing_hashes = set()
    for w in main_payroll.get("weeks", []):
        for e in w.get("entries", []):
            existing_hashes.add(compute_entry_hash(e))

    added = 0
    for week in temp_payroll.get("weeks", []):
        week_period = week["week_period"]
        filtered = []
        for e in week.get("entries", []):
            h = compute_entry_hash(e)
            if h not in existing_hashes:
                filtered.append(e)
                existing_hashes.add(h)
                added += 1
        if not filtered:
            continue
        # Find or create week in main payroll
        found = False
        for mw in main_payroll["weeks"]:
            if mw["week_period"] == week_period:
                mw["entries"].extend(filtered)
                found = True
                break
        if not found:
            main_payroll["weeks"].append({"week_period": week_period, "entries": filtered})

    main_payroll["submitted"] = True
    main_payroll["submitted_at"] = now_iso
    main_payroll["metadata"] = meta

    # Store totals inside the payroll, not at document root
    p_total, p_billable, p_non_billable = recalc_payroll_totals(main_payroll)
    main_payroll["totalHours"] = p_total
    main_payroll["totalBillableHours"] = p_billable
    main_payroll["totalNonBillableHours"] = p_non_billable

    emp_info = {
        "employeeName": meta.get("employeeName", ""),
        "designation": meta.get("designation", ""),
        "gender": meta.get("gender", ""),
        "partner": meta.get("partner", ""),
        "reportingManager": meta.get("reportingManager", ""),
    }

    payload = {
        **emp_info,
        "payrolls": existing_payrolls,
        "updated_time": now_iso,
    }
    # Remove legacy root-level total fields if they exist
    timesheets_collection.update_one(
        {"employeeId": emp_id},
        {"$unset": {"totalHours": "", "totalBillableHours": "", "totalNonBillableHours": ""}}
    ) if existing_doc else None

    if existing_doc:
        timesheets_collection.update_one({"employeeId": emp_id}, {"$set": payload})
    else:
        payload["employeeId"] = emp_id
        payload["created_time"] = now_iso
        timesheets_collection.insert_one(payload)

    # Mark temp payroll as submitted
    for p in temp_doc.get("payrolls", []):
        if p.get("cycle_id") == cycle_id:
            p["submitted"] = True
            p["submitted_at"] = now_iso
    timesheet_temp_collection.update_one(
        {"employeeId": emp_id},
        {"$set": {"payrolls": temp_doc["payrolls"], "updated_time": now_iso}}
    )

    # Update Pending collection
    try:
        emp_doc = employee_details_collection.find_one({"EmpID": emp_id})
        if emp_doc:
            mgr_code = emp_doc.get("ReportingEmpCode", "").strip().upper()
            mgr_name = emp_doc.get("ReportingEmpName", "Unknown")
            if mgr_code:
                approved_collection.update_one({"ReportingEmpCode": mgr_code}, {"$pull": {"EmployeesCodes": emp_id}})
                rejected_collection.update_one({"ReportingEmpCode": mgr_code}, {"$pull": {"EmployeesCodes": emp_id}})
                add_or_create(pending_collection, mgr_code, mgr_name, emp_id)
    except Exception as e:
        print(f"Error updating Pending: {e}")

    return {"success": True, "message": "Timesheet submitted successfully", "added": added}


@router.get("/list/{employee_id}")
async def get_timesheets(employee_id: str, current_user: str = Depends(get_current_user)):
    """Return all payrolls with their weeks and entries."""
    if employee_id != current_user:
        raise HTTPException(status_code=403, detail="Unauthorized")

    doc = timesheets_collection.find_one({"employeeId": employee_id})
    if not doc:
        return {
            "success": True,
            "payrolls": [],
            "totalHours": 0,
            "totalBillableHours": 0,
            "totalNonBillableHours": 0,
        }

    # Fetch payroll cycles to get show_lunch_travel flag
    from backend.database import payroll_cycles_collection
    from bson import ObjectId as BsonObjectId
    
    payrolls_out = []
    for p in doc.get("payrolls", []):
        weeks_out = []
        for w in p.get("weeks", []):
            entries_out = []
            for e in w.get("entries", []):
                entries_out.append({
                    **e,
                    "weekPeriod": w["week_period"],
                    "cycle_id": p["cycle_id"],
                    "cycle_label": p.get("cycle_label", ""),
                    "submitted": p.get("submitted", False),
                    "submitted_at": p.get("submitted_at"),
                    "employeeId": doc.get("employeeId", ""),
                    "employeeName": doc.get("employeeName", ""),
                    "designation": doc.get("designation", ""),
                    "reportingManager": doc.get("reportingManager", ""),
                    "hits": p.get("metadata", {}).get("hits", ""),
                    "misses": p.get("metadata", {}).get("misses", ""),
                    "feedback_hr": p.get("metadata", {}).get("feedback_hr", ""),
                    "feedback_it": p.get("metadata", {}).get("feedback_it", ""),
                    "feedback_crm": p.get("metadata", {}).get("feedback_crm", ""),
                    "feedback_others": p.get("metadata", {}).get("feedback_others", ""),
                })
            weeks_out.append({
                "week_period": w["week_period"],
                "entries": entries_out,
            })

        # Per-payroll totals (stored in payroll or recalculated)
        p_total = p.get("totalHours") or recalc_payroll_totals(p)[0]
        p_billable = p.get("totalBillableHours") or recalc_payroll_totals(p)[1]
        p_non_billable = p.get("totalNonBillableHours") or recalc_payroll_totals(p)[2]
        if not p.get("totalHours"):
            p_total, p_billable, p_non_billable = recalc_payroll_totals(p)

        # Fetch show_lunch_travel flag from payroll_cycles collection
        show_lunch_travel = True  # default
        try:
            cycle_doc = payroll_cycles_collection.find_one({"_id": BsonObjectId(p["cycle_id"])})
            if cycle_doc:
                show_lunch_travel = cycle_doc.get("show_lunch_travel", True)
        except Exception as e:
            print(f"Error fetching cycle config: {e}")

        payrolls_out.append({
            "cycle_id": p["cycle_id"],
            "cycle_label": p.get("cycle_label", ""),
            "submitted": p.get("submitted", False),
            "submitted_at": p.get("submitted_at"),
            "metadata": p.get("metadata", {}),
            "totalHours": p_total,
            "totalBillableHours": p_billable,
            "totalNonBillableHours": p_non_billable,
            "show_lunch_travel": show_lunch_travel,
            "weeks": weeks_out,
        })

    return {
        "success": True,
        "payrolls": payrolls_out,
    }


@router.put("/update/{employee_id}/{entry_id}")
async def update_timesheet(
    employee_id: str,
    entry_id: str,
    update_data: UpdateTimesheetRequest,
    current_user: str = Depends(get_current_user),
):
    if employee_id != current_user:
        raise HTTPException(status_code=403, detail="Unauthorized")

    now_iso = datetime.utcnow().isoformat()
    doc = timesheets_collection.find_one({"employeeId": employee_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    updated = False
    for p in doc.get("payrolls", []):
        for w in p.get("weeks", []):
            for i, entry in enumerate(w.get("entries", [])):
                if entry.get("id") == entry_id:
                    w["entries"][i] = {**entry, **update_data.dict(exclude_none=True), "updated_time": now_iso, "id": entry_id}
                    updated = True
                    break
            if updated:
                break
        if updated:
            break

    if not updated:
        raise HTTPException(status_code=404, detail="Entry not found")

    # Recalc totals per payroll
    for p in doc["payrolls"]:
        pt, pb, pnb = recalc_payroll_totals(p)
        p["totalHours"] = pt
        p["totalBillableHours"] = pb
        p["totalNonBillableHours"] = pnb

    timesheets_collection.update_one(
        {"employeeId": employee_id},
        {"$set": {
            "payrolls": doc["payrolls"],
            "updated_time": now_iso,
        }, "$unset": {"totalHours": "", "totalBillableHours": "", "totalNonBillableHours": ""}},
    )
    return {"success": True, "message": "Entry updated"}


@router.delete("/delete/{employee_id}/{entry_id}")
async def delete_timesheet(
    employee_id: str,
    entry_id: str,
    current_user: str = Depends(get_current_user),
):
    if employee_id != current_user:
        raise HTTPException(status_code=403, detail="Unauthorized")

    now_iso = datetime.utcnow().isoformat()
    doc = timesheets_collection.find_one({"employeeId": employee_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    found = False
    for p in doc.get("payrolls", []):
        for w in p.get("weeks", []):
            orig_len = len(w.get("entries", []))
            w["entries"] = [e for e in w.get("entries", []) if e.get("id") != entry_id]
            if len(w["entries"]) != orig_len:
                found = True
        p["weeks"] = [w for w in p.get("weeks", []) if w.get("entries")]

    if not found:
        raise HTTPException(status_code=404, detail="Entry not found")

    # Recalc totals per payroll
    for p in doc["payrolls"]:
        pt, pb, pnb = recalc_payroll_totals(p)
        p["totalHours"] = pt
        p["totalBillableHours"] = pb
        p["totalNonBillableHours"] = pnb

    timesheets_collection.update_one(
        {"employeeId": employee_id},
        {"$set": {
            "payrolls": doc["payrolls"],
            "updated_time": now_iso,
        }, "$unset": {"totalHours": "", "totalBillableHours": "", "totalNonBillableHours": ""}},
    )
    return {"success": True, "message": "Entry deleted"}


@router.get("/employees")
async def get_employees(current_user: str = Depends(get_current_user)):
    return list(employee_details_collection.find({}, {"_id": 0}))


@router.get("/clients")
async def get_clients(current_user: str = Depends(get_current_user)):
    return list(client_details_collection.find({}, {"_id": 0}))


@router.get("/projects/{employee_id}")
async def get_employee_projects(employee_id: str, current_user: str = Depends(get_current_user)):
    if employee_id != current_user:
        raise HTTPException(status_code=403, detail="Unauthorized")

    employee = employee_details_collection.find_one({"EmpID": employee_id})
    if not employee:
        return {"clients": [], "projects_by_client": {}}

    partner_code = employee.get("PartnerEmpCode", "").strip().upper()
    if not partner_code:
        return {"clients": [], "projects_by_client": {}}

    projects = list(db["Projects"].find({"partner_emp_code": partner_code}))
    projects_by_client: dict = {}
    for p in projects:
        client = p.get("client_name", "").strip()
        proj_name = p.get("project_name", "").strip()
        proj_code = p.get("project_code", "").strip()
        if not (client and proj_name and proj_code):
            continue
        projects_by_client.setdefault(client, [])
        if not any(x["project_name"] == proj_name for x in projects_by_client[client]):
            projects_by_client[client].append({"project_name": proj_name, "project_code": proj_code})

    for c in projects_by_client:
        projects_by_client[c].sort(key=lambda x: x["project_name"])

    return {"clients": sorted(projects_by_client.keys()), "projects_by_client": projects_by_client}


@router.get("/check-manager/{emp_code}")
async def check_reporting_manager(emp_code: str, current_user: str = Depends(get_current_user)):
    doc = reporting_managers_collection.find_one({"ReportingEmpCode": emp_code.strip().upper()})
    return {"isManager": bool(doc)}


@router.get("/view/{employee_id}")
async def get_employee_timesheet_for_manager(
    employee_id: str,
    cycle_id: Optional[str] = None,
):
    """Return employee timesheet for manager view. Optional cycle_id filters to one payroll cycle."""
    doc = timesheets_collection.find_one({"employeeId": employee_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="No timesheet found")

    entries = []
    cycle_label_shown = ""
    meta = {}
    for p in doc.get("payrolls", []):
        if cycle_id and p.get("cycle_id") != cycle_id:
            continue  # skip other cycles when a specific one is requested
        cycle_label_shown = p.get("cycle_label", "")
        meta = p.get("metadata", {}) or {}
        for w in p.get("weeks", []):
            for e in w.get("entries", []):
                entries.append({
                    "weekPeriod": w["week_period"],
                    "cycle_label": p.get("cycle_label", ""),
                    "date": e.get("date", ""),
                    "client": e.get("client", ""),
                    "project": e.get("project", ""),
                    "activity": e.get("activity", ""),
                    "location": e.get("location", ""),
                    "start_time": e.get("projectStartTime", ""),
                    "end_time": e.get("projectEndTime", ""),
                    "hours": e.get("projectHours", ""),
                    "billable": e.get("billable", ""),
                    "lunchTime": e.get("lunchTime", ""),
                    "travelTime": e.get("travelTime", ""),
                    "remarks": e.get("remarks", ""),
                })

    return {
        "employee_id": doc.get("employeeId"),
        "employee_name": doc.get("employeeName"),
        "designation": doc.get("designation"),
        "gender": doc.get("gender"),
        "partner": doc.get("partner"),
        "reporting_manager": doc.get("reportingManager"),
        "cycle_label": cycle_label_shown,
        "hits": meta.get("hits", ""),
        "misses": meta.get("misses", ""),
        "feedback_hr": meta.get("feedback_hr", ""),
        "feedback_it": meta.get("feedback_it", ""),
        "feedback_crm": meta.get("feedback_crm", ""),
        "feedback_others": meta.get("feedback_others", ""),
        "entries": entries,
    }


def _get_current_live_cycle_ids() -> list:
    """Return cycle_ids of all currently live payroll cycles."""
    from backend.database import payroll_cycles_collection
    cycles = list(payroll_cycles_collection.find({"status": "live"}, {"_id": 1}))
    return [str(c["_id"]) for c in cycles]


def _get_approval_cycle_ids() -> list:
    """Return cycle_ids to use for approval screens.

    If admin has set an active_approval_cycle_id, return only that.
    Otherwise fall back to all live cycles.
    """
    from backend.database import admin_details_collection, payroll_cycles_collection
    admin = admin_details_collection.find_one({}, {"active_approval_cycle_id": 1})
    if admin and admin.get("active_approval_cycle_id"):
        return [admin["active_approval_cycle_id"]]
    cycles = list(payroll_cycles_collection.find({"status": "live"}, {"_id": 1}))
    return [str(c["_id"]) for c in cycles]


def _find_best_payroll(payrolls: list, preferred_cycle_ids: list) -> dict | None:
    """Find the most relevant payroll to display for approval screens.

    Priority:
    1. Submitted payroll matching the active approval cycle
    2. Any other submitted payroll (handles cross-cycle pending like April-May still awaiting)
    Returns None only if employee has no submitted payrolls at all.
    """
    # Priority 1: active cycle, submitted
    for p in reversed(payrolls):
        if p.get("cycle_id") in preferred_cycle_ids and p.get("submitted"):
            return p
    # Priority 2: any submitted payroll (most recent first)
    for p in reversed(payrolls):
        if p.get("submitted"):
            return p
    return None


def _get_employees_by_status(reporting_emp_code: str, coll_name: str):
    coll = db[coll_name]
    doc = coll.find_one({"ReportingEmpCode": reporting_emp_code})
    if not doc:
        return {"employees": []}

    approval_cycle_ids = _get_approval_cycle_ids()

    result = []
    for code in doc.get("EmployeesCodes", []):
        ts = timesheets_collection.find_one({"employeeId": code}, {"_id": 0})
        if not ts:
            # Employee has no timesheet data at all — still include with empty info
            result.append({
                "employeeId": code,
                "cycle_id": "",
                "timesheetData": {
                    "employeeId": code,
                    "employeeName": "",
                    "designation": "",
                    "cycle_label": "No data",
                    "approval_status": None,
                }
            })
            continue

        best = _find_best_payroll(ts.get("payrolls", []), approval_cycle_ids)
        cycle_label = best.get("cycle_label", "") if best else "Not submitted"
        cycle_id    = best.get("cycle_id", "") if best else ""
        approval_status = best.get("approval_status") if best else None

        result.append({
            "employeeId": code,
            "cycle_id": cycle_id,
            "timesheetData": {
                "employeeId": code,
                "employeeName": ts.get("employeeName", ""),
                "designation": ts.get("designation", ""),
                "cycle_label": cycle_label,
                "approval_status": approval_status,
            }
        })

    return {"reporting_manager": reporting_emp_code, "employees": result}


@router.get("/pending/{reporting_emp_code}")
async def get_pending(reporting_emp_code: str, current_user: str = Depends(get_current_user)):
    code = (reporting_emp_code or current_user).strip().upper()
    return _get_employees_by_status(code, "Pending")


@router.get("/approved/{reporting_emp_code}")
async def get_approved(reporting_emp_code: str, current_user: str = Depends(get_current_user)):
    return _get_employees_by_status(reporting_emp_code.strip().upper(), "Approved")


@router.get("/rejected/{reporting_emp_code}")
async def get_rejected(reporting_emp_code: str, current_user: str = Depends(get_current_user)):
    return _get_employees_by_status(reporting_emp_code.strip().upper(), "Rejected")


def _set_payroll_approval_status(employee_code: str, status: str, approved_by: str = "", approved_by_name: str = "",
                                  rejected_at: str = "", reason: str = "", preferred_cycle_ids: list = None):
    """Write approval_status into the employee's most relevant payroll in Timesheet_data."""
    ts = timesheets_collection.find_one({"employeeId": employee_code}, {"payrolls": 1})
    if not ts:
        return
    best = _find_best_payroll(ts.get("payrolls", []), preferred_cycle_ids or [])
    if not best:
        return
    now_iso = datetime.utcnow().isoformat()
    update_fields = {
        "payrolls.$[elem].approval_status": status,
        "payrolls.$[elem].status_updated_at": now_iso,
    }
    if status == "approved":
        update_fields["payrolls.$[elem].approved_by"]      = approved_by
        update_fields["payrolls.$[elem].approved_by_name"] = approved_by_name
        update_fields["payrolls.$[elem].approved_at"]      = now_iso
    elif status == "rejected":
        update_fields["payrolls.$[elem].rejected_by"]      = approved_by
        update_fields["payrolls.$[elem].rejected_by_name"] = approved_by_name
        update_fields["payrolls.$[elem].rejected_at"]      = rejected_at or now_iso
        update_fields["payrolls.$[elem].rejection_reason"] = reason
    timesheets_collection.update_one(
        {"employeeId": employee_code},
        {"$set": update_fields},
        array_filters=[{"elem.cycle_id": best["cycle_id"]}],
    )


@router.post("/approve")
async def approve_timesheet(
    reporting_emp_code: str = Body(...),
    employee_code: str = Body(...),
    current_user: str = Depends(get_current_user),
):
    mgr = reporting_emp_code.strip().upper()
    emp = employee_code.strip().upper()
    pending_collection.update_one({"ReportingEmpCode": mgr}, {"$pull": {"EmployeesCodes": emp}})
    rejected_collection.update_one({"ReportingEmpCode": mgr}, {"$pull": {"EmployeesCodes": emp}})
    mgr_doc = employee_details_collection.find_one({"ReportingEmpCode": mgr})
    mgr_name = mgr_doc.get("ReportingEmpName") if mgr_doc else "Unknown"
    add_or_create(approved_collection, mgr, mgr_name, emp)
    # Write approval_status into Timesheet_data
    _set_payroll_approval_status(
        emp, "approved",
        approved_by=mgr, approved_by_name=mgr_name,
        preferred_cycle_ids=_get_approval_cycle_ids(),
    )
    return {"success": True, "message": f"Employee {emp} approved"}


@router.post("/reject")
async def reject_timesheet(
    reporting_emp_code: str = Body(...),
    employee_code: str = Body(...),
    reason: str = Body(default=""),
    current_user: str = Depends(get_current_user),
):
    mgr = reporting_emp_code.strip().upper()
    emp = employee_code.strip().upper()
    now_iso = datetime.utcnow().isoformat()
    pending_collection.update_one({"ReportingEmpCode": mgr}, {"$pull": {"EmployeesCodes": emp}})
    approved_collection.update_one({"ReportingEmpCode": mgr}, {"$pull": {"EmployeesCodes": emp}})
    mgr_doc = employee_details_collection.find_one({"ReportingEmpCode": mgr})
    mgr_name = mgr_doc.get("ReportingEmpName") if mgr_doc else "Unknown"
    add_or_create(rejected_collection, mgr, mgr_name, emp)
    # Store rejection reason in Rejected collection
    rejected_collection.update_one(
        {"ReportingEmpCode": mgr},
        {"$set": {
            f"rejection_details.{emp}.reason": reason,
            f"rejection_details.{emp}.rejected_at": now_iso,
            f"rejection_details.{emp}.rejected_by": mgr,
            f"rejection_details.{emp}.rejected_by_name": mgr_name,
        }},
    )
    # Write approval_status into Timesheet_data
    _set_payroll_approval_status(
        emp, "rejected",
        approved_by=mgr, approved_by_name=mgr_name,
        rejected_at=now_iso, reason=reason,
        preferred_cycle_ids=_get_approval_cycle_ids(),
    )
    return {"success": True, "message": f"Employee {emp} rejected"}


@router.post("/approve-all")
async def approve_all(data: ApproveAllRequest, current_user: str = Depends(get_current_user)):
    mgr = data.reporting_emp_code.strip().upper()
    source = data.source.strip().title()
    if source not in ["Pending", "Rejected"]:
        raise HTTPException(status_code=400, detail="source must be Pending or Rejected")
    src_coll = pending_collection if source == "Pending" else rejected_collection
    doc = src_coll.find_one({"ReportingEmpCode": mgr})
    if not doc or not doc.get("EmployeesCodes"):
        return {"success": True, "approved": 0, "message": "No employees to approve"}
    employees = doc["EmployeesCodes"]
    pending_collection.update_one({"ReportingEmpCode": mgr}, {"$pull": {"EmployeesCodes": {"$in": employees}}})
    rejected_collection.update_one({"ReportingEmpCode": mgr}, {"$pull": {"EmployeesCodes": {"$in": employees}}})
    mgr_doc = employee_details_collection.find_one({"ReportingEmpCode": mgr})
    mgr_name = mgr_doc.get("ReportingEmpName") if mgr_doc else "Unknown"
    approval_cycle_ids = _get_approval_cycle_ids()
    for emp in employees:
        add_or_create(approved_collection, mgr, mgr_name, emp)
        _set_payroll_approval_status(
            emp, "approved",
            approved_by=mgr, approved_by_name=mgr_name,
            preferred_cycle_ids=approval_cycle_ids,
        )
    return {"success": True, "approved": len(employees), "message": f"{len(employees)} employee(s) approved"}


@router.get("/approval-tracker/{employee_id}")
async def get_approval_tracker(employee_id: str, current_user: str = Depends(get_current_user)):
    """Return per-payroll approval status for an employee.

    Primary source: approval_status stored directly in Timesheet_data payroll.
    Fallback: check Pending/Approved/Rejected collections for legacy data without stored status.
    """
    emp = employee_id.strip().upper()
    ts = timesheets_collection.find_one({"employeeId": emp}, {"_id": 0, "payrolls": 1})
    if not ts:
        return {"statuses": []}

    # Fallback: check collections for employees that pre-date status tracking
    pending_doc  = pending_collection.find_one({"EmployeesCodes": emp})
    approved_doc = approved_collection.find_one({"EmployeesCodes": emp})
    rejected_doc = rejected_collection.find_one({"EmployeesCodes": emp})

    rejection_detail = {}
    if rejected_doc:
        rejection_detail = (rejected_doc.get("rejection_details") or {}).get(emp, {})

    statuses = []
    for p in (ts.get("payrolls") or []):
        # Prefer approval_status stored on the payroll itself (set by approve/reject/bulk actions)
        stored_status = p.get("approval_status")

        if not p.get("submitted"):
            status = "draft"
        elif stored_status:
            status = stored_status  # trust the stored value
        elif approved_doc:
            status = "approved"
        elif rejected_doc:
            status = "rejected"
        elif pending_doc:
            status = "pending"
        else:
            status = "submitted"

        statuses.append({
            "cycle_id":         p.get("cycle_id"),
            "cycle_label":      p.get("cycle_label"),
            "submitted":        p.get("submitted", False),
            "submitted_at":     p.get("submitted_at"),
            "status":           status,
            "approved_by":      p.get("approved_by", ""),
            "approved_by_name": p.get("approved_by_name", ""),
            "approved_at":      p.get("approved_at"),
            "rejected_by":      p.get("rejected_by", "") or rejection_detail.get("rejected_by", ""),
            "rejected_by_name": p.get("rejected_by_name", "") or rejection_detail.get("rejected_by_name", ""),
            "rejected_at":      p.get("rejected_at") or rejection_detail.get("rejected_at"),
            "rejection_reason": p.get("rejection_reason", "") or rejection_detail.get("reason", ""),
        })

    return {"statuses": statuses}
