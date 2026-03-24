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
db = _client["staging_Timesheet"]
appraisal_db = _client["staging_Appraisal"]

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
forgot_password_otps_collection = db["forgot_password_otps"]

# ── appraisal collections (add when ready) ────────────────────────────────────
appraisal_collection          = appraisal_db["Appraisal_data"]
