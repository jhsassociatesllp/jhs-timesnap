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
client_details_collection     = db["Client_details"]
reporting_managers_collection = db["Reporting_managers"]
pending_collection            = db["Pending"]
approved_collection           = db["Approved"]
rejected_collection           = db["Rejected"]

# ── admin collections ─────────────────────────────────────────────────────────
admin_details_collection      = db["admin_details"]
appraisal_admin_collection = appraisal_db["Admin"]
forgot_password_otps_collection = db["forgot_password_otps"]

# ── module admin access collection ───────────────────────────────────────────
# Document shape: { "empid": "JHS001", "modules": ["timesheet", "quality_audit", "kra"] }
module_admin_collection       = db["module_admin_access"]

# ── appraisal collections (add when ready) ────────────────────────────────────
appraisal_collection          = appraisal_db["Appraisal_data"]

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
# One doc per employee per cycle:
# { employeeId, cycle_id, cycle_label, Data: [{weekPeriod: [entries]}],
#   submitted: false, metadata: {empName, designation, ...} }
timesheet_temp_collection     = db["Timesheet_temp"]
