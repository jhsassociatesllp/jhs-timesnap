# backend/cycle/store.py
"""Collection handles for the cycle review and digest, in one place so tests can swap them."""
from backend.timesheet import scope
from backend.database import (
    approval_history_collection,
    approved_collection,
    config_collection,
    cycle_reviews_collection,
    daily_reco_collection,
    day_drafts_collection,
    day_submissions_collection,
    email_log_collection,
    employee_details_collection,
    hrms_attendance_collection,
    hrms_uploads_collection,
    job_runs_collection,
    payroll_cycles_collection,
    pending_collection,
    rejected_collection,
    timesheet_entries_collection,
    timesheet_payrolls_collection,
    timesheets_collection,
)

CONFIG_ID = "timesheet"


class _Store:
    entries = timesheet_entries_collection
    payrolls = timesheet_payrolls_collection
    submissions = day_submissions_collection
    drafts = day_drafts_collection
    hrms = hrms_attendance_collection
    uploads = hrms_uploads_collection
    reco = daily_reco_collection
    reviews = cycle_reviews_collection
    email_log = email_log_collection
    job_runs = job_runs_collection
    config = config_collection
    employees = employee_details_collection
    # classic (legacy) collections: only backend.cycle.mirror writes to them
    legacy = timesheets_collection
    payroll_cycles = payroll_cycles_collection
    pending = pending_collection
    approved = approved_collection
    rejected = rejected_collection
    approval_history = approval_history_collection


store = _Store()


def config_doc() -> dict:
    return store.config.find_one({"_id": CONFIG_ID}) or {}


def pilot_set() -> set:
    """Employees on the new timesheet: everyone (except free-text employees), or only the pilot list."""
    return scope.enabled_set(store.config, store.employees)


def holidays_set() -> set:
    return {str(h)[:10] for h in config_doc().get("holidays", []) or []}
