# backend/database.py
"""
Single source of truth for all MongoDB collections.
Both the timesheet and appraisal routers import from here.
"""

import os
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

MONGO_CONNECTION_STRING = os.getenv("MONGO_CONNECTION_STRING")
if not MONGO_CONNECTION_STRING:
    raise ValueError("MONGO_CONNECTION_STRING env var is required")

_client = MongoClient(MONGO_CONNECTION_STRING)
db = _client["Timesheets"]
appraisal_db = _client["Appraisal"]

# ── shared collections ────────────────────────────────────────────────────────
sessions_collection           = db["sessions"]
employee_details_collection   = db["Employee_details"]
users_collection              = db["users"]

# ── timesheet collections ─────────────────────────────────────────────────────
timesheets_collection         = db["Timesheet_data"]
<<<<<<< HEAD
client_details_collection     = db["Projects"]
=======
client_details_collection     = db["Client_details"]
>>>>>>> origin/main
reporting_managers_collection = db["Reporting_managers"]
pending_collection            = db["Pending"]
approved_collection           = db["Approved"]
rejected_collection           = db["Rejected"]

# ── approval audit trail ──────────────────────────────────────────────────────
# Append-only log of submit/resubmit/reject/approve events, one document per
# event: { employeeId, employeeName, cycle_id, cycle_label, action, actor_code,
#   actor_name, reason, timestamp }. Powers the manager-facing history tracker
# and future analytics (e.g. rejection frequency per employee per month).
approval_history_collection   = db["Approval_History"]

# ── admin collections ─────────────────────────────────────────────────────────
admin_details_collection      = db["admin_details"]
appraisal_admin_collection = appraisal_db["Admin"]
forgot_password_otps_collection = db["forgot_password_otps"]

# ── module admin access collection ───────────────────────────────────────────
# Document shape: { "empid": "JHS001", "modules": ["timesheet", "quality_audit", "kra"] }
module_admin_collection       = db["module_admin_access"]

# ── appraisal collections (add when ready) ────────────────────────────────────
appraisal_collection          = appraisal_db["Appraisal_data"]

<<<<<<< HEAD
# ── appraisal (KRA) quarter/cycle collections ─────────────────────────────────
# Document shape:
# {
#   "quarter_id": "KRA_Q2_2026_27",     # stable, slugified from the label at creation
#   "quarter_label": "Q2 2026-27",      # display value, editable
#   "status": "draft" | "live" | "closed",
#   "created_at": datetime, "created_by": str,
#   "updated_at": datetime, "updated_by": str,
# }
# Only one cycle may be "live" at a time — activating one auto-closes the rest.
appraisal_cycles_collection   = appraisal_db["Appraisal_cycles"]

# One doc per (quarter, employee) — who is allowed to fill the KRA for that
# quarter. An Excel upload for a quarter fully REPLACES its rows.
# { "quarter_id": str, "employee_code": str, "employee_name": str,
#   "uploaded_at": datetime, "uploaded_by": str }
appraisal_eligibility_collection = appraisal_db["Appraisal_eligibility"]

# Audit log, one doc per eligibility-list upload — powers the Admin Panel's
# validation report and upload history.
# { "quarter_id": str, "uploaded_by": str, "uploaded_at": datetime,
#   "filename": str, "total_records": int, "valid_count": int,
#   "invalid_count": int, "duplicate_count": int, "invalid_rows": [...] }
appraisal_upload_history_collection = appraisal_db["Appraisal_upload_history"]

=======
>>>>>>> origin/main
# ── payroll cycles collection ─────────────────────────────────────────────────
# Document shape:
# {
#   "cycle_label": "Apr-May 2025",
#   "start_date": "2025-04-21",
#   "end_date": "2025-05-20",
#   "deadline_date": "2025-05-23",
#   "deadline_time": "18:30",          # 24h format, IST
#   "status": "live" | "upcoming" | "closed",
#   "created_at": datetime
# }
payroll_cycles_collection     = db["payroll_cycles"]

# ── timesheet temp (draft) collection ────────────────────────────────────────
# One doc per employee: { employeeId, payrolls: [{ cycle_id, cycle_label,
#   submitted, entries: [ {id, date, ...} ], metadata: {empName, ...} }] }
# Entries are flat (no week grouping) — see backend/timesheet/router.py's
# module docstring for the full shape and the read-side backward-compat note.
timesheet_temp_collection     = db["Timesheet_temp"]
