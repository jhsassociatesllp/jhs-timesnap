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

# ── per-module databases (split out of "Timesheets") ──────────────────────────
# Mongo database names cannot contain spaces, hence the underscores.
cv_db         = _client["CV_Builder"]         # cv_profiles, cv_custom_options, cv_experience
referral_db   = _client["Buddy_Referral"]     # buddy_* collections + buddy_referral_resumes GridFS
compliance_db = _client["Compliance_Table"]   # compliance_calendar_items

# ── shared collections ────────────────────────────────────────────────────────
sessions_collection           = db["sessions"]
employee_details_collection   = db["Employee_details"]
users_collection              = db["users"]

# ── timesheet collections ─────────────────────────────────────────────────────
timesheets_collection         = db["Timesheet_data"]
client_details_collection     = db["Projects"]
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

# ── project-tracking collections (daily hours-only timesheet) ─────────────────
# timesheet_entries: ONE document per entry line (not nested). Fields: employee_id,
#   date (YYYY-MM-DD), task_id, project_code, client, project (copied from NQ),
#   activity, hours, task_status, is_unplanned, unplanned_reason, cycle_id,
#   approved, locked, created_at, updated_at (+ task_name, awaiting_hrms).
# day_submissions: employee_id, date, submitted_at, reco_reason, cycle_id.
# hrms_attendance: filled by the HRMS upload (Phase 3); read-only here.
# config: {_id: "timesheet", standard_hours, lunch_hours, tolerance,
#          pilot_employees: [...], holidays: ["YYYY-MM-DD", ...]}.
timesheet_entries_collection  = db["timesheet_entries"]
day_submissions_collection    = db["day_submissions"]
hrms_attendance_collection    = db["hrms_attendance"]
config_collection             = db["config"]
hrms_uploads_collection       = db["hrms_uploads"]
daily_reco_collection         = db["daily_reco"]
# cycle_reviews: kind "approval" {cycle_id, employee_id, status, approved_by/at, history[]} and
#   kind "reestimate" {cycle_id, task_id, project_code, old/new end date, hours_needed, actor, ...}.
cycle_reviews_collection      = db["cycle_reviews"]
# email_log: one row per mail attempt (never the body): kind, key, to, subject, status, error.
email_log_collection          = db["email_log"]
# job_runs: one row per scheduled job per day so only one process ever runs it.
job_runs_collection           = db["job_runs"]
