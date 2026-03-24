# backend/timesheet/router.py
import hashlib
import json
from datetime import datetime
from typing import List

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, status, Body

from backend.database import (
    timesheets_collection,
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


def recalc_totals(data: list) -> tuple:
    total = billable = non_billable = 0.0
    for week_obj in data:
        for _, entries in week_obj.items():
            for e in entries:
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


# ───────────────────────────── routes ────────────────────────────────────────

@router.post("/save")
async def save_timesheets(
    entries: List[TimesheetEntry],
    current_user: str = Depends(get_current_user),
):
    if not entries:
        return {"success": False, "message": "No entries provided"}

    normalized = [e.dict() if hasattr(e, "dict") else e for e in entries]

    for e in normalized:
        if e.get("employeeId") != current_user:
            raise HTTPException(status_code=403, detail="Cannot save for another employee")

    emp_id = current_user
    now_iso = datetime.utcnow().isoformat()

    # Group by weekPeriod
    week_data: dict = {}
    for e in normalized:
        week = e.get("weekPeriod") or "Uncategorized"
        week_data.setdefault(week, []).append({
            "date": e.get("date", ""),
            "location": e.get("location", ""),
            "projectStartTime": e.get("projectStartTime", ""),
            "projectEndTime": e.get("projectEndTime", ""),
            "client": e.get("client", ""),
            "project": e.get("project", ""),
            "projectCode": e.get("projectCode", ""),
            "reportingManagerEntry": e.get("reportingManagerEntry", ""),
            "activity": e.get("activity", ""),
            "projectHours": e.get("projectHours", "0"),
            "billable": e.get("billable", "No"),
            "remarks": e.get("remarks", ""),
            "id": str(ObjectId()),
            "created_time": now_iso,
            "updated_time": now_iso,
        })

    existing_doc = timesheets_collection.find_one({"employeeId": emp_id})
    existing_data = existing_doc.get("Data", []) if existing_doc else []

    existing_hashes = set()
    for wk in existing_data:
        for _, wk_entries in wk.items():
            for entry in wk_entries:
                existing_hashes.add(compute_entry_hash(entry))

    new_week_objects = []
    added = skipped = 0

    for week_name, new_entries in week_data.items():
        filtered = []
        for entry in new_entries:
            h = compute_entry_hash(entry)
            if h not in existing_hashes:
                filtered.append(entry)
                existing_hashes.add(h)
                added += 1
            else:
                skipped += 1
        if filtered:
            new_week_objects.append({week_name: filtered})

    if not new_week_objects:
        return {"success": True, "message": "No new unique data to save", "added": 0, "skipped": skipped}

    # Merge
    if existing_doc and existing_data:
        merged = existing_data.copy()
        for new_wk in new_week_objects:
            wk_name = list(new_wk.keys())[0]
            found = False
            for ex_wk in merged:
                if wk_name in ex_wk:
                    ex_wk[wk_name].extend(new_wk[wk_name])
                    found = True
                    break
            if not found:
                merged.append(new_wk)
        final_data = merged
    else:
        final_data = new_week_objects

    total, billable_hrs, non_billable_hrs = recalc_totals(final_data)
    first = normalized[0]

    payload = {
        "employeeId": emp_id,
        "employeeName": first.get("employeeName", ""),
        "designation": first.get("designation", ""),
        "gender": first.get("gender", ""),
        "partner": first.get("partner", ""),
        "reportingManager": first.get("reportingManager", ""),
        "Data": final_data,
        "hits": first.get("hits", ""),
        "misses": first.get("misses", ""),
        "feedback_hr": first.get("feedback_hr", ""),
        "feedback_it": first.get("feedback_it", ""),
        "feedback_crm": first.get("feedback_crm", ""),
        "feedback_others": first.get("feedback_others", ""),
        "updated_time": now_iso,
        "totalHours": total,
        "totalBillableHours": billable_hrs,
        "totalNonBillableHours": non_billable_hrs,
    }

    if existing_doc:
        timesheets_collection.update_one({"employeeId": emp_id}, {"$set": payload})
    else:
        payload["created_time"] = now_iso
        timesheets_collection.insert_one(payload)

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
        print(f"Error updating Pending for {emp_id}: {e}")

    return {"success": True, "message": "Timesheet saved", "added": added, "skipped": skipped}


@router.get("/list/{employee_id}")
async def get_timesheets(employee_id: str, current_user: str = Depends(get_current_user)):
    if employee_id != current_user:
        raise HTTPException(status_code=403, detail="Unauthorized")

    doc = timesheets_collection.find_one({"employeeId": employee_id})
    if not doc:
        return {"success": True, "Data": [], "totalHours": 0, "totalBillableHours": 0, "totalNonBillableHours": 0}

    emp_info = {k: doc.get(k, "") for k in [
        "employeeId", "Name", "designation", "gender", "partner",
        "reportingManager", "hits", "misses",
        "feedback_hr", "feedback_it", "feedback_crm", "feedback_others",
        "totalHours", "totalBillableHours", "totalNonBillableHours",
    ]}

    flat = []
    for wk in doc.get("Data", []):
        for period, entries in wk.items():
            for entry in entries:
                flat.append({**emp_info, **entry, "weekPeriod": period})

    return {
        "success": True,
        "Data": flat,
        "totalHours": emp_info["totalHours"],
        "totalBillableHours": emp_info["totalBillableHours"],
        "totalNonBillableHours": emp_info["totalNonBillableHours"],
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
    for wk in doc.get("Data", []):
        for period, entries in wk.items():
            for i, entry in enumerate(entries):
                if entry.get("id") == entry_id:
                    entries[i] = {**entry, **update_data.dict(exclude_none=True), "updated_time": now_iso, "id": entry_id}
                    updated = True
                    break
        if updated:
            break

    if not updated:
        raise HTTPException(status_code=404, detail="Entry not found")

    total, billable_hrs, non_billable_hrs = recalc_totals(doc["Data"])
    timesheets_collection.update_one(
        {"employeeId": employee_id},
        {"$set": {"Data": doc["Data"], "updated_time": now_iso,
                  "totalHours": total, "totalBillableHours": billable_hrs,
                  "totalNonBillableHours": non_billable_hrs}},
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
    new_data = []
    for wk in doc.get("Data", []):
        new_wk = {}
        for period, entries in wk.items():
            filtered = [e for e in entries if e.get("id") != entry_id]
            if len(filtered) != len(entries):
                found = True
            if filtered:
                new_wk[period] = filtered
        if new_wk:
            new_data.append(new_wk)

    if not found:
        raise HTTPException(status_code=404, detail="Entry not found")

    total, billable_hrs, non_billable_hrs = recalc_totals(new_data)
    timesheets_collection.update_one(
        {"employeeId": employee_id},
        {"$set": {"Data": new_data, "updated_time": now_iso,
                  "totalHours": total, "totalBillableHours": billable_hrs,
                  "totalNonBillableHours": non_billable_hrs}},
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
async def get_employee_timesheet_for_manager(employee_id: str):
    doc = timesheets_collection.find_one({"employeeId": employee_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="No timesheet found")

    entries = []
    for wk in doc.get("Data", []):
        for period, wk_entries in wk.items():
            for e in wk_entries:
                entries.append({
                    "weekPeriod": period,
                    "date": e.get("date", ""),
                    "client": e.get("client", ""),
                    "project": e.get("project", ""),
                    "activity": e.get("activity", ""),
                    "location": e.get("location", ""),
                    "start_time": e.get("projectStartTime", ""),
                    "end_time": e.get("projectEndTime", ""),
                    "hours": e.get("projectHours", ""),
                    "billable": e.get("billable", ""),
                    "remarks": e.get("remarks", ""),
                })

    return {
        "employee_id": doc.get("employeeId"),
        "employee_name": doc.get("Name"),
        "designation": doc.get("designation"),
        "gender": doc.get("gender"),
        "partner": doc.get("partner"),
        "reporting_manager": doc.get("reportingManager"),
        "entries": entries,
        "hits": doc.get("hits", ""),
        "misses": doc.get("misses", ""),
        "feedback_hr": doc.get("feedback_hr", ""),
        "feedback_it": doc.get("feedback_it", ""),
        "feedback_crm": doc.get("feedback_crm", ""),
        "feedback_others": doc.get("feedback_others", ""),
    }


def _get_employees_by_status(reporting_emp_code: str, coll_name: str):
    coll = db[coll_name]
    doc = coll.find_one({"ReportingEmpCode": reporting_emp_code})
    if not doc:
        return {"employees": []}

    result = []
    for code in doc.get("EmployeesCodes", []):
        ts = timesheets_collection.find_one({"employeeId": code}, {"_id": 0})
        result.append({"employeeId": code, "timesheetData": ts})
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

    return {"success": True, "message": f"Employee {emp} approved"}


@router.post("/reject")
async def reject_timesheet(
    reporting_emp_code: str = Body(...),
    employee_code: str = Body(...),
    current_user: str = Depends(get_current_user),
):
    mgr = reporting_emp_code.strip().upper()
    emp = employee_code.strip().upper()

    pending_collection.update_one({"ReportingEmpCode": mgr}, {"$pull": {"EmployeesCodes": emp}})
    approved_collection.update_one({"ReportingEmpCode": mgr}, {"$pull": {"EmployeesCodes": emp}})

    mgr_doc = employee_details_collection.find_one({"ReportingEmpCode": mgr})
    mgr_name = mgr_doc.get("ReportingEmpName") if mgr_doc else "Unknown"
    add_or_create(rejected_collection, mgr, mgr_name, emp)

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
    for emp in employees:
        add_or_create(approved_collection, mgr, mgr_name, emp)

    return {"success": True, "approved": len(employees), "message": f"{len(employees)} employee(s) approved"}
