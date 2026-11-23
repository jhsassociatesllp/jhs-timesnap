# backend/exit_management/repository.py
"""MongoDB access for the Employee Exit Management module.

Reuses the platform's shared client/database (backend.database) - no new
connection. All data lives in ONE collection, `exist_form`, with exactly one
document per employee (unique `employee_id`). The document's `status` moves
draft -> submitted, so there is never a separate draft record to clean up.
"""
import logging
from typing import Optional

import gridfs
from pymongo import ASCENDING
from pymongo.errors import PyMongoError

from backend.database import db, employee_details_collection

log = logging.getLogger("exit_management")

COLLECTION_NAME = "exist_form"
collection = db[COLLECTION_NAME]

# Signature files (PDF / JPG / PNG, max 5 MB) live in GridFS - the form document only keeps a reference.
# Who may approve the IT and HR stages: one document per person {stage: "it" | "hr", empid: "JHS123"}.
# (The Reporting Manager stage is decided per form from the employee's own record.) Edit it in Compass.
approvers = db["exit_approvers"]

# Who may complete IT Clearance (for every employee's exit form): one document per person {empid: "JHS123", active: true}.
# Give or take away access in Compass: insert { "empid": "JHS123" } to grant, set "active": false to revoke.
# Filled with the three starting IT approvers the first time it is read while still empty.
it_approvers = db["it_clearance_approvers"]
DEFAULT_IT_APPROVERS = ("JHS722", "JHS1474", "JHS1551")

# Who may complete HR Clearance (for every employee's exit form): one document per person {empid: "JHS123", active: true}.
# Give or take away access in Compass: insert { "empid": "JHS123" } to grant, set "active": false to revoke.
# Filled with the two starting HR approvers the first time it is read while still empty.
hr_approvers = db["hr_clearance_approvers"]
DEFAULT_HR_APPROVERS = ("JHS1423", "JHS911")

SIGNATURE_BUCKET = "signature_files"
signature_bucket = gridfs.GridFSBucket(db, bucket_name=SIGNATURE_BUCKET)
_indexes_ready = False


def ensure_indexes() -> None:
    """Create the indexes once per process (MongoDB ignores existing ones)."""
    global _indexes_ready
    if _indexes_ready:
        return
    try:
        collection.create_index([("employee_id", ASCENDING)], unique=True, name="uniq_employee_id")
        collection.create_index([("status", ASCENDING)], name="status")
        collection.create_index([("approval.current_stage", ASCENDING)], name="approval_stage")
        collection.create_index([("approval.reporting_manager.expected_approver_code", ASCENDING)], name="approval_rm")
        approvers.create_index([("stage", ASCENDING), ("empid", ASCENDING)], unique=True, name="uniq_stage_empid")
        it_approvers.create_index([("empid", ASCENDING)], unique=True, name="uniq_it_empid")
        hr_approvers.create_index([("empid", ASCENDING)], unique=True, name="uniq_hr_empid")
        db[SIGNATURE_BUCKET + ".files"].create_index([("metadata.employee_id", ASCENDING)], name="signature_employee")
        _indexes_ready = True
    except PyMongoError:
        log.exception("Could not create exist_form indexes")


def it_approver_ids() -> set:
    """EmpIDs allowed to complete IT Clearance (active documents of `it_clearance_approvers`)."""
    if it_approvers.count_documents({}, limit=1) == 0:
        for code in DEFAULT_IT_APPROVERS:
            it_approvers.update_one({"empid": code}, {"$setOnInsert": {"empid": code, "active": True}}, upsert=True)
    return {str(d.get("empid") or "").strip().upper() for d in it_approvers.find({"active": {"$ne": False}})} - {""}


def hr_approver_ids() -> set:
    """EmpIDs allowed to complete HR Clearance (active documents of `hr_clearance_approvers`)."""
    if hr_approvers.count_documents({}, limit=1) == 0:
        for code in DEFAULT_HR_APPROVERS:
            hr_approvers.update_one({"empid": code}, {"$setOnInsert": {"empid": code, "active": True}}, upsert=True)
    return {str(d.get("empid") or "").strip().upper() for d in hr_approvers.find({"active": {"$ne": False}})} - {""}


def find_employee(empid: str) -> Optional[dict]:
    """The employee's row in the shared Employee_details collection (read-only)."""
    return employee_details_collection.find_one({"EmpID": empid})


def find_form(empid: str) -> Optional[dict]:
    ensure_indexes()
    return collection.find_one({"employee_id": empid})


def find_team(manager_code: str) -> list:
    """Employees whose reporting manager is `manager_code`, straight from Employee_details (read-only)."""
    if not manager_code:
        return []
    return list(employee_details_collection.find(
        {"ReportingEmpCode": manager_code, "EmpID": {"$ne": manager_code}}).sort("Emp Name", 1))      # never the manager themself
