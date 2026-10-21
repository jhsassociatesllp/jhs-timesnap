# backend/cycle/store.py
"""Collection handles for the cycle review and digest, in one place so tests can swap them."""
from backend.database import (
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
    timesheet_entries_collection,
)

CONFIG_ID = "timesheet"


class _Store:
    entries = timesheet_entries_collection
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


store = _Store()


def config_doc() -> dict:
    return store.config.find_one({"_id": CONFIG_ID}) or {}


def pilot_set() -> set:
    return {str(e).strip().upper() for e in config_doc().get("pilot_employees", []) or []}


def holidays_set() -> set:
    return {str(h)[:10] for h in config_doc().get("holidays", []) or []}
