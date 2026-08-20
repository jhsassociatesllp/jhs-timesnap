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
      "entries": [ { "id": "...", "date": "...", ... } ]
    }
  ],
  "updated_time": "...",
  "created_time": "..."
}

Entries are flat under each payroll — there is no week-wise grouping. Older
documents written before this change may still have their entries nested
under a "weeks": [{"week_period": ..., "entries": [...]}] list instead;
_get_payroll_entries() transparently flattens those on read, and any
mutating endpoint (save-draft, update, delete, submit) rewrites the payroll
in the flat shape, so a document migrates itself the next time it's touched.
"""
import re
from datetime import datetime, timedelta
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
    approval_history_collection,
    db,
)
from backend.auth import get_current_user
from backend.timesheet.models import (
    TimesheetEntry,
    UpdateTimesheetRequest,
    ApproveAllRequest,
)

router = APIRouter(prefix="/timesheet", tags=["Timesheet"])

# Partner whose employees have no fixed client/project list — those fields
# are free-typed in the app instead of dropdowns, and their project codes
# aren't required to follow the PL-prefix convention.
FREE_TEXT_PARTNER_CODE = "JHS01"

# Locations that mean "not a working day" — lunch time / project code aren't
# applicable for rows marked with these.
DAY_OFF_LOCATIONS = {"Leave", "PHY", "Week Off"}
# Travel is not applicable for a day off, working from home, or working from
# the office. Lunch is additionally not applicable for a day off.
NO_TRAVEL_TIME_LOCATIONS = DAY_OFF_LOCATIONS | {"Work From Home", "Office"}


# ─────────────────────────── helpers ────────────────────────────────────────


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


def _get_payroll_entries(payroll: dict) -> list:
    """Flat entries for a payroll. New documents store them directly under
    "entries"; older documents still have them nested under "weeks" —
    flatten those transparently so both shapes read the same."""
    if "entries" in payroll:
        return payroll.get("entries") or []
    entries = []
    for w in payroll.get("weeks", []) or []:
        entries.extend(w.get("entries", []) or [])
    return entries


def _normalize_payroll_entries(payroll: dict) -> list:
    """Like _get_payroll_entries, but also migrates the payroll dict in
    place to the flat shape (drops "weeks") so the next save stays flat."""
    entries = _get_payroll_entries(payroll)
    payroll["entries"] = entries
    payroll.pop("weeks", None)
    return entries


def _parse_employment_date(value) -> Optional[datetime]:
    """Parse the date values stored in ``Employee_details`` safely.

    The current employee master stores Date of Joining and Date of Exit as
    ``DD/MM/YYYY`` strings.  ISO values and datetime values are accepted too
    so a future data-format change does not turn a valid submission into a
    server error.  An unknown/malformed value intentionally returns ``None``:
    the completeness check then retains its existing full-cycle behaviour.
    """
    if not value:
        return None
    if isinstance(value, datetime):
        return value.replace(hour=0, minute=0, second=0, microsecond=0)

    value = str(value).strip()
    for date_format in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value[:10], date_format)
        except ValueError:
            pass
    return None


def _required_timesheet_dates(cycle_start: datetime, cycle_end: datetime, employee: Optional[dict]) -> set:
    """Return payroll dates for which this employee must have an entry.

    Only the overlap between the payroll cycle and the employee's recorded
    employment interval is required.  Missing/invalid employment dates do not
    relax the current rule: the full cycle remains required in that case.
    """
    applicable_start = cycle_start
    applicable_end = cycle_end
    employee = employee or {}

    joining_date = _parse_employment_date(employee.get("Date of Joining"))
    exit_date = _parse_employment_date(employee.get("Date of Exit"))
    if joining_date and joining_date > applicable_start:
        applicable_start = joining_date
    if exit_date and exit_date < applicable_end:
        applicable_end = exit_date

    required_dates = set()
    current_date = applicable_start
    while current_date <= applicable_end:
        required_dates.add(current_date.strftime("%Y-%m-%d"))
        current_date += timedelta(days=1)
    return required_dates


def recalc_totals_from_payrolls(payrolls: list) -> tuple:
    """Recalc totals for the entire document (sum of all payrolls)."""
    total = billable = non_billable = 0.0
    for payroll in payrolls:
        for e in _get_payroll_entries(payroll):
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
    for e in _get_payroll_entries(payroll):
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
        "entries": [],
    }
    payrolls.append(new_payroll)
    return new_payroll


# ───────────────────────────── routes ────────────────────────────────────────

@router.post("/save-draft")
async def save_draft(
    cycle_id: str = Body(...),
    cycle_label: str = Body(...),
    entries: list = Body(...),
    metadata: dict = Body(default={}),
    current_user: str = Depends(get_current_user),
):
    """Save the whole cycle's entries as draft (Timesheet_temp), flat — no week grouping.

    A draft save persists whatever the user has filled in so far, with no
    completeness checks — those (lunch time, mandatory fields, PL-prefix
    codes) are enforced at submit time instead, so partially-filled rows
    never block saving progress.
    """
    now_iso = datetime.utcnow().isoformat()

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
        payroll["entries"] = new_entries
        payroll.pop("weeks", None)
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
            "entries": new_entries,
        }
        timesheet_temp_collection.insert_one({
            "employeeId": current_user,
            "payrolls": [payroll],
            "created_time": now_iso,
            "updated_time": now_iso,
        })

    return {"success": True, "message": "Draft saved"}


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
            p = dict(p)
            p["entries"] = _get_payroll_entries(p)
            p.pop("weeks", None)
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
    temp_entries = _get_payroll_entries(temp_payroll)

    # Keep not-applicable time fields consistently empty in both the submitted
    # timesheet and the locked draft. This also makes older drafts conform when
    # they are submitted after a location is changed.
    for entry in temp_entries:
        location = (entry.get("location", "") or "").strip()
        if location in DAY_OFF_LOCATIONS:
            entry["lunchTime"] = ""
            entry["billable"] = "No"
        if location in NO_TRAVEL_TIME_LOCATIONS:
            entry["travelTime"] = ""

    from backend.database import payroll_cycles_collection
    try:
        cycle_doc = payroll_cycles_collection.find_one({"_id": ObjectId(cycle_id)})
    except Exception:
        cycle_doc = None

    # The employee master is the source of the employment window used by the
    # completeness gate below.  Rows outside that window are not applicable
    # timesheet rows, so they must not trigger row-level submit validation
    # either (older drafts may contain auto-created rows for those dates).
    submit_employee = employee_details_collection.find_one({"EmpID": current_user})
    required_dates = None
    if cycle_doc and cycle_doc.get("start_date") and cycle_doc.get("end_date"):
        start_d = datetime.fromisoformat(str(cycle_doc["start_date"])[:10])
        end_d = datetime.fromisoformat(str(cycle_doc["end_date"])[:10])
        required_dates = _required_timesheet_dates(start_d, end_d, submit_employee)

    validation_entries = temp_entries
    if required_dates is not None:
        validation_entries = [
            entry for entry in temp_entries
            if not entry.get("date") or (entry.get("date", "") or "")[:10] in required_dates
        ]

    # ── Lunch-time gate ─────────────────────────────────────────────────
    show_lunch_travel = cycle_doc.get("show_lunch_travel", True) if cycle_doc else True
    if show_lunch_travel:
        lunch_errors = []
        for i, entry in enumerate(validation_entries):
            if (entry.get("location", "") or "").strip() in DAY_OFF_LOCATIONS:
                continue  # not a working day — lunch time isn't applicable
            lt = entry.get("lunchTime", "") or ""
            if not lt.strip():
                lunch_errors.append(f"Row {i + 1}: Lunch Time is required")
        if lunch_errors:
            raise HTTPException(400, "Cannot submit — " + "; ".join(lunch_errors[:5]))

    # ── Mandatory fields gate ───────────────────────────────────────────
    # Every working-day row must be fully filled in before the timesheet can
    # be submitted (draft saves allow partial rows; this is the final check).
    mandatory_fields = [
        "date", "projectStartTime", "projectEndTime", "client", "project",
        "projectCode", "reportingManagerEntry", "activity",
    ]
    field_errors = []
    for i, entry in enumerate(validation_entries):
        if (entry.get("location", "") or "").strip() in DAY_OFF_LOCATIONS:
            continue
        for field in mandatory_fields:
            if not (entry.get(field, "") or "").strip():
                field_errors.append(f"Row {i + 1}: {field} is required")
    if field_errors:
        raise HTTPException(400, "Cannot submit — " + "; ".join(field_errors[:5]))

    # ── PL-prefix gate ──────────────────────────────────────────────────
    # Non-JHS01 partners must use real Nexus Quant project codes (all start
    # with "PL"). Day-off rows have no project to charge, so they're exempt.
    # A row where the employee picked "Other" as the Client (no matching
    # project in their assigned list) is exempt from the PL-prefix rule too,
    # but must have its Project Code literally set to "Other".
    submit_partner_code = (submit_employee.get("PartnerEmpCode", "") if submit_employee else "").strip().upper()
    if submit_partner_code != FREE_TEXT_PARTNER_CODE:
        code_errors = []
        for i, entry in enumerate(validation_entries):
            if (entry.get("location", "") or "").strip() in DAY_OFF_LOCATIONS:
                continue
            client = (entry.get("client", "") or "").strip().upper()
            code = (entry.get("projectCode", "") or "").strip().upper()
            if client == "OTHER":
                if code != "OTHER":
                    code_errors.append(f'Row {i + 1}: project code must be "Other" when Client is "Other"')
                continue
            if not code.startswith("PL"):
                code_errors.append(f"Row {i + 1}: project code must start with \"PL\" (Nexus Quant only)")
        if code_errors:
            raise HTTPException(400, "Cannot submit — " + "; ".join(code_errors[:5]))

    # ── Day-completeness gate ────────────────────────────────────────────
    # Every calendar day applicable to the employee in the payroll cycle must
    # have at least one entry row before the timesheet can be submitted (a
    # Leave/Week Off/PHY row still counts).  Days before Date of Joining and
    # after Date of Exit in Employee_details are not applicable.
    if cycle_doc and cycle_doc.get("start_date") and cycle_doc.get("end_date"):
        present_dates = {(e.get("date", "") or "")[:10] for e in temp_entries if e.get("date")}
        missing_dates = sorted(required_dates - present_dates)
        if missing_dates:
            extra = f" and {len(missing_dates) - 10} more" if len(missing_dates) > 10 else ""
            raise HTTPException(
                400,
                "Cannot submit — missing entries for: " + ", ".join(missing_dates[:10]) + extra,
            )

    # ── TL project-plan gate ──────────────────────────────────────────────
    # TLs (reporting managers) must have a valid project plan matching the
    # project code for every working-day entry before they can submit. This
    # never blocks saving a draft, only the final submit. JHS01 TLs are
    # shared services and don't create/track projects this way, so they're
    # exempt. Entry dates are NOT checked against the plan's task window —
    # only whether a matching plan exists.
    is_tl = bool(reporting_managers_collection.find_one({"ReportingEmpCode": emp_id.strip().upper()}))
    employee = employee_details_collection.find_one({"EmpID": emp_id.strip().upper()}, {"_id": 0, "PartnerEmpCode": 1})
    partner_code = (employee.get("PartnerEmpCode", "") if employee else "").strip().upper()
    if is_tl and partner_code != FREE_TEXT_PARTNER_CODE:
        plan_cache = {}
        plan_errors = []
        for entry in validation_entries:
            location = (entry.get("location", "") or "").strip()
            if location in DAY_OFF_LOCATIONS:
                continue
            # "Other" entries have no fixed project to look up a plan for —
            # same exemption as the PL-prefix check at save-draft time.
            if (entry.get("client", "") or "").strip().upper() == "OTHER":
                continue
            code = (entry.get("projectCode", "") or "").strip().upper()
            entry_date_str = entry.get("date", "") or ""
            if code not in plan_cache:
                plan_cache[code] = _lookup_project_plan(code)
            has_plan, _plan_start, _plan_end = plan_cache[code]
            if not has_plan:
                plan_errors.append(f'{entry_date_str}: no project plan found for code "{code}"')
        if plan_errors:
            raise HTTPException(
                400,
                "Cannot submit — some entries have no matching project plan: "
                + "; ".join(plan_errors[:8]),
            )

    # Publish draft → main. save-draft always fully replaces the temp
    # payroll's entries (never appends), so temp_entries is the complete,
    # current state of this cycle — submit therefore replaces the main
    # payroll's entries wholesale too. Merging/deduping against the old main
    # entries here (as this used to do) left superseded rows behind any time
    # an entry's content changed, most visibly after a TL rejection + edit +
    # resubmit: the old row and the corrected row would both survive as
    # "different" entries since their content (and hash) differed.
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
            "entries": [],
        }
        existing_payrolls.append(main_payroll)

    # Capture prior state before overwriting, to tell the audit log apart —
    # a resubmission that follows a rejection is worth distinguishing from a
    # first-time submit.
    was_previously_submitted = main_payroll.get("submitted", False)
    was_previously_rejected = main_payroll.get("approval_status") == "rejected"

    main_payroll["entries"] = temp_entries
    main_payroll.pop("weeks", None)
    main_payroll["submitted"] = True
    main_payroll["submitted_at"] = now_iso
    main_payroll["metadata"] = meta
    # A fresh resubmission supersedes any prior verdict — it goes back into
    # the approval queue as a new decision, not still flagged as rejected.
    main_payroll["approval_status"] = None

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

    # Audit trail entry — lets the tracker (and future rejection analytics)
    # distinguish a first-time submit from a resubmission that followed a
    # rejection. Carries a full snapshot of what was submitted, since main
    # entries get overwritten on the next submit — this is the only place
    # this exact version survives for later viewing.
    approval_history_collection.insert_one({
        "employeeId": emp_id,
        "employeeName": meta.get("employeeName", ""),
        "cycle_id": cycle_id,
        "cycle_label": cycle_label,
        "action": "resubmitted" if (was_previously_submitted and was_previously_rejected) else "submitted",
        "actor_code": emp_id,
        "actor_name": meta.get("employeeName", ""),
        "reason": "",
        "timestamp": now_iso,
        "entries": temp_entries,
    })

    return {"success": True, "message": "Timesheet submitted successfully", "added": len(temp_entries)}


@router.get("/list/{employee_id}")
async def get_timesheets(employee_id: str, current_user: str = Depends(get_current_user)):
    """Return all payrolls with their flat entries."""
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
        entries_out = []
        for e in _get_payroll_entries(p):
            entries_out.append({
                **e,
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
                "idle_time": p.get("metadata", {}).get("idle_time", ""),
                "idle_time_status": p.get("metadata", {}).get("idle_time_status", ""),
                "idle_time_hours": p.get("metadata", {}).get("idle_time_hours", ""),
                "idle_time_reason": p.get("metadata", {}).get("idle_time_reason", ""),
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
            "entries": entries_out,
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
        entries = _normalize_payroll_entries(p)
        for i, entry in enumerate(entries):
            if entry.get("id") == entry_id:
                entries[i] = {**entry, **update_data.dict(exclude_none=True), "updated_time": now_iso, "id": entry_id}
                updated = True
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
        entries = _normalize_payroll_entries(p)
        orig_len = len(entries)
        p["entries"] = [e for e in entries if e.get("id") != entry_id]
        if len(p["entries"]) != orig_len:
            found = True

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
        return {"clients": [], "projects_by_client": {}, "partner_emp_code": ""}

    partner_code = employee.get("PartnerEmpCode", "").strip().upper()
    if not partner_code:
        return {"clients": [], "projects_by_client": {}, "partner_emp_code": ""}

    # Company-wide: every client/project is available to every dropdown-mode
    # employee, not just the ones belonging to their own partner — they pick
    # a client first, which then narrows the project list to that client's own.
    projects = list(db["Projects"].find({}))
    projects_by_client: dict = {}
    for p in projects:
        client = p.get("client_name", "").strip()
        proj_name = p.get("project_name", "").strip()
        proj_code = p.get("project_code", "").strip()
        if not (client and proj_name and proj_code):
            continue
        projects_by_client.setdefault(client, [])
        if not any(x["project_name"] == proj_name for x in projects_by_client[client]):
            projects_by_client[client].append({
                "project_name": proj_name,
                "project_code": proj_code,
                "execution_start_date": p.get("execution_start_date", ""),
                "execution_end_date": p.get("execution_end_date", ""),
            })

    for c in projects_by_client:
        projects_by_client[c].sort(key=lambda x: x["project_name"])

    return {
        "clients": sorted(projects_by_client.keys()),
        "projects_by_client": projects_by_client,
        "partner_emp_code": partner_code,
    }


@router.get("/check-manager/{emp_code}")
async def check_reporting_manager(emp_code: str, current_user: str = Depends(get_current_user)):
    doc = reporting_managers_collection.find_one({"ReportingEmpCode": emp_code.strip().upper()})
    # Also fetch the employee's PartnerEmpCode so the frontend can detect shared services
    emp_doc = employee_details_collection.find_one({"EmpID": emp_code.strip().upper()}, {"_id": 0, "PartnerEmpCode": 1})
    partner_emp_code = (emp_doc.get("PartnerEmpCode", "") if emp_doc else "").strip().upper()
    return {"isManager": bool(doc), "partnerEmpCode": partner_emp_code}


def _lookup_project_plan(project_code: str):
    """Whether a project plan has been created for this project code (Project_Plans
    collection — a plan is just its presence there, any tasks at all), and if so
    the execution window to show/validate against, taken from the Projects
    collection's execution_start_date/execution_end_date (the project's own
    planned dates, not the individual tasks' dates). Returns (has_plan, start_date,
    end_date) — dates as datetime objects, or None when there is no plan/project."""
    code = (project_code or "").strip().upper()
    if not code:
        return False, None, None
    escaped = re.escape(code)
    plan_query = {
        "$or": [
            {"project_code": {"$regex": f"^{escaped}$", "$options": "i"}},
            {"project_id": {"$regex": f"^{escaped}$", "$options": "i"}},
            {"ProjectCode": {"$regex": f"^{escaped}$", "$options": "i"}},
            {"ProjectId": {"$regex": f"^{escaped}$", "$options": "i"}},
        ]
    }
    has_plan = db["Project_Plans"].find_one(plan_query, {"_id": 1}) is not None
    if not has_plan:
        # Legacy/alternate collection name — kept for environments that use it
        has_plan = db["Project Plans"].find_one(plan_query, {"_id": 1}) is not None
    if not has_plan:
        return False, None, None

    project_doc = db["Projects"].find_one(
        {"project_code": {"$regex": f"^{escaped}$", "$options": "i"}},
        {"_id": 0, "execution_start_date": 1, "execution_end_date": 1},
    )
    start_date = project_doc.get("execution_start_date") if project_doc else None
    end_date = project_doc.get("execution_end_date") if project_doc else None
    return True, start_date, end_date


@router.get("/project-plan-status/{project_code}")
async def get_project_plan_status(project_code: str, current_user: str = Depends(get_current_user)):
    """Check whether a project plan has been created for the given project_code,
    and if so, its execution window (from the Projects collection)."""
    has_plan, start_date, end_date = _lookup_project_plan(project_code)
    return {
        "project_code": project_code,
        "has_plan": has_plan,
        "start_date": start_date.isoformat() if start_date else None,
        "end_date": end_date.isoformat() if end_date else None,
    }


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
        for e in _get_payroll_entries(p):
            entries.append({
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
        "idle_time": meta.get("idle_time", ""),
        "idle_time_status": meta.get("idle_time_status", ""),
        "idle_time_hours": meta.get("idle_time_hours", ""),
        "idle_time_reason": meta.get("idle_time_reason", ""),
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


def _find_best_payroll(payrolls: list, preferred_cycle_ids: list, strict: bool = False) -> dict | None:
    """Find the most relevant payroll to display for approval screens.

    Priority:
    1. Submitted payroll matching the active approval cycle
    2. Any other submitted payroll (handles cross-cycle pending like April-May still awaiting)
       — skipped when strict=True, so callers can restrict results to the
       currently selected/active payroll cycle only.
    Returns None only if employee has no matching submitted payrolls.
    """
    # Priority 1: active cycle, submitted
    for p in reversed(payrolls):
        if p.get("cycle_id") in preferred_cycle_ids and p.get("submitted"):
            return p
    if strict:
        return None
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
            # No timesheet data at all — can't belong to the selected cycle
            continue

        # Only show employees whose submission matches the currently
        # selected/active payroll cycle — other cycles are excluded, not
        # just deprioritized.
        best = _find_best_payroll(ts.get("payrolls", []), approval_cycle_ids, strict=True)
        if not best:
            continue
        cycle_label = best.get("cycle_label", "")
        cycle_id    = best.get("cycle_id", "")
        approval_status = best.get("approval_status")

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
    """Write approval_status into the employee's most relevant payroll in Timesheet_data,
    and record the action in the Approval_History audit trail."""
    ts = timesheets_collection.find_one({"employeeId": employee_code}, {"payrolls": 1, "employeeName": 1})
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
    event_timestamp = now_iso
    if status == "approved":
        update_fields["payrolls.$[elem].approved_by"]      = approved_by
        update_fields["payrolls.$[elem].approved_by_name"] = approved_by_name
        update_fields["payrolls.$[elem].approved_at"]      = now_iso
    elif status == "rejected":
        event_timestamp = rejected_at or now_iso
        update_fields["payrolls.$[elem].rejected_by"]      = approved_by
        update_fields["payrolls.$[elem].rejected_by_name"] = approved_by_name
        update_fields["payrolls.$[elem].rejected_at"]      = event_timestamp
        update_fields["payrolls.$[elem].rejection_reason"] = reason
    timesheets_collection.update_one(
        {"employeeId": employee_code},
        {"$set": update_fields},
        array_filters=[{"elem.cycle_id": best["cycle_id"]}],
    )
    approval_history_collection.insert_one({
        "employeeId": employee_code,
        "employeeName": ts.get("employeeName", ""),
        "cycle_id": best.get("cycle_id", ""),
        "cycle_label": best.get("cycle_label", ""),
        "action": status,
        "actor_code": approved_by,
        "actor_name": approved_by_name,
        "entries": _get_payroll_entries(best),
        "reason": reason if status == "rejected" else "",
        "timestamp": event_timestamp,
    })


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


@router.get("/approval-history/{employee_id}")
async def get_approval_history(
    employee_id: str,
    cycle_id: Optional[str] = None,
    current_user: str = Depends(get_current_user),
):
    """Full audit trail (submit/resubmit/reject/approve) for an employee, oldest
    first — the manager-facing tracker of how a timesheet's approval played out,
    e.g. rejected → resubmitted → approved. Pass cycle_id to scope to one cycle."""
    emp = employee_id.strip().upper()
    query = {"employeeId": emp}
    if cycle_id:
        query["cycle_id"] = cycle_id
    events = list(approval_history_collection.find(query, {"_id": 0}).sort("timestamp", 1))
    return {"events": events}
