"""
Cycle / digest tests use the Docker dev Mongo (27018) and its scratch database
'timesnap_test'. They never touch .env, real data, or real mail (mailer.send_mail is stubbed).
"""
import os
import socket
from datetime import datetime

import pytest

os.environ.setdefault("MONGO_CONNECTION_STRING", "mongodb://localhost:27018/")

from pymongo import MongoClient

from backend.cycle.store import store

PORT = int(os.getenv("MONGO_DEV_PORT", "27018"))
DAY = "2026-10-14"        # a Wednesday, in cycle 2026-10-C2


def _up():
    s = socket.socket()
    s.settimeout(1)
    try:
        return s.connect_ex(("127.0.0.1", PORT)) == 0
    finally:
        s.close()


@pytest.fixture
def cdb(monkeypatch):
    if not _up():
        pytest.skip("dev Mongo not running (docker compose -f docker-compose.dev.yml up -d)")
    db = MongoClient(f"mongodb://127.0.0.1:{PORT}/")["timesnap_test"]
    names = {"entries": "c_entries", "submissions": "c_submissions", "hrms": "c_hrms", "uploads": "c_uploads",
             "reco": "c_reco", "reviews": "c_reviews", "email_log": "c_email_log", "job_runs": "c_job_runs",
             "config": "c_config", "employees": "c_employees",
             "legacy": "c_legacy", "payroll_cycles": "c_pcycles", "pending": "c_pending", "approved": "c_approved",
             "rejected": "c_rejected", "approval_history": "c_apphist"}
    for attr, coll in names.items():
        db[coll].drop()
        monkeypatch.setattr(store, attr, db[coll])
    # the HRMS reco module has its own store handle: point it at the same scratch collections
    from backend.hrms import reco as hrms_reco
    for attr in ("entries", "submissions", "hrms", "uploads", "reco", "config", "employees"):
        monkeypatch.setattr(hrms_reco.store, attr, db[names[attr]])
    db["c_config"].insert_one({"_id": "timesheet", "timesheet_scope": "pilot", "pilot_employees": ["JHS9101", "JHS9102", "JHS9103"],
                               "holidays": ["2026-10-02"]})
    db["c_employees"].insert_many([
        {"EmpID": "JHS9101", "Emp Name": "Emp One", "ReportingEmpCode": "JHS9001", "EMail": "e1@example.invalid"},
        {"EmpID": "JHS9102", "Emp Name": "Emp Two", "ReportingEmpCode": "JHS9001", "EMail": "e2@example.invalid"},
        {"EmpID": "JHS9103", "Emp Name": "Emp Three", "ReportingEmpCode": "JHS9002", "EMail": "e3@example.invalid"},
        {"EmpID": "JHS9104", "Emp Name": "Not Pilot", "ReportingEmpCode": "JHS9001", "EMail": "e4@example.invalid"},
        {"EmpID": "JHS9001", "Emp Name": "Manager A", "ReportingEmpCode": "JHS9000", "EMail": "mgr.a@example.invalid"},
        {"EmpID": "JHS9002", "Emp Name": "Manager B", "ReportingEmpCode": "JHS9000", "EMail": "mgr.b@example.invalid"},
        {"EmpID": "JHS9000", "Emp Name": "Admin Person", "ReportingEmpCode": "", "EMail": "admin@example.invalid"},
    ])
    return db


def entry(emp, day, hours, status="done", **kw):
    now = datetime.utcnow()
    return {"employee_id": emp, "date": day, "task_id": 1, "task_name": "Task X", "activity": "worked",
            "hours": hours, "task_status": status, "is_unplanned": False, "unplanned_reason": "",
            "project_code": "PL-T001", "awaiting_hrms": False, "approved": False, "locked": False,
            "cycle_id": "2026-10-C2", "created_at": now, "updated_at": now, **kw}
