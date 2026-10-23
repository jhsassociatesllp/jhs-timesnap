"""
API tests for HRMS upload + reconciliation. Need the Docker dev Mongo (27018); they use a scratch
database 'timesnap_test' and never touch .env or real data. Dates follow tests/hrms/sample.py.
"""
import os
import socket
from datetime import date, datetime

import pytest

os.environ.setdefault("MONGO_CONNECTION_STRING", "mongodb://localhost:27018/")

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pymongo import MongoClient

from backend.auth import get_current_user
from backend.hrms import reco
from backend.hrms import router as hrms_router
from tests.hrms import sample

PORT = int(os.getenv("MONGO_DEV_PORT", "27018"))


def _up():
    s = socket.socket()
    s.settimeout(1)
    try:
        return s.connect_ex(("127.0.0.1", PORT)) == 0
    finally:
        s.close()


pytestmark = pytest.mark.skipif(not _up(), reason="dev Mongo not running (docker compose -f docker-compose.dev.yml up -d)")

_user = {"id": "JHS9000"}
ADMINS = {"JHS9000"}


@pytest.fixture
def api(monkeypatch):
    db = MongoClient(f"mongodb://127.0.0.1:{PORT}/")["timesnap_test"]
    names = {"entries": "h_entries", "submissions": "h_submissions", "hrms": "h_hrms", "uploads": "h_uploads",
             "reco": "h_reco", "config": "h_config", "employees": "h_employees"}
    for attr, coll in names.items():
        db[coll].drop()
        monkeypatch.setattr(reco.store, attr, db[coll])
    db["h_config"].insert_one({"_id": "timesheet", "timesheet_scope": "pilot", "pilot_employees": ["JHS9101", "JHS9102", "JHS9103"]})
    db["h_employees"].insert_many([
        {"EmpID": "JHS9101", "Emp Name": "Emp One", "ReportingEmpCode": "JHS9001"},
        {"EmpID": "JHS9102", "Emp Name": "Emp Two", "ReportingEmpCode": "JHS9001"},
        {"EmpID": "JHS9103", "Emp Name": "Emp Three", "ReportingEmpCode": "JHS9002"},
        {"EmpID": "JHS9001", "Emp Name": "Manager A", "ReportingEmpCode": "JHS9000"},
        {"EmpID": "JHS9002", "Emp Name": "Manager B", "ReportingEmpCode": "JHS9000"},
    ])
    monkeypatch.setattr(hrms_router, "has_admin_module", lambda emp, key: emp in ADMINS and key == "timesheet")
    monkeypatch.setattr(hrms_router, "_today", lambda: date(2026, 10, 16))
    app = FastAPI()
    app.include_router(hrms_router.router)
    app.dependency_overrides[get_current_user] = lambda: _user["id"]
    _user["id"] = "JHS9000"
    c = TestClient(app)
    c.db = db
    yield c


def entry(emp, day, hours, **kw):
    now = datetime.utcnow()
    return {"employee_id": emp, "date": day, "task_id": 1, "activity": "x", "hours": hours,
            "task_status": "done", "is_unplanned": False, "awaiting_hrms": hours is None,
            "approved": False, "locked": False, "created_at": now, "updated_at": now, **kw}


def upload(c, path, content=None, name="hrms.xlsx"):
    return c.post(path, files={"file": (name, content if content is not None else sample.build_bytes(),
                                        "application/octet-stream")})


def seed_entries(c):
    ins = c.db["h_entries"].insert_many
    ins([entry("JHS9101", "2026-10-12", 4), entry("JHS9101", "2026-10-12", 4.5),          # 8.5 vs 8.5 -> matched
         entry("JHS9101", "2026-10-13", 9.25),                                            # one task, typed 9.25 = HRMS net
         entry("JHS9102", "2026-10-12", 4), entry("JHS9102", "2026-10-12", 1),            # 5.0 vs 7.0 -> short
         entry("JHS9102", "2026-10-14", 3),                                               # no punch but entries
         entry("JHS9103", "2026-10-14", 3), entry("JHS9103", "2026-10-14", 3)])           # 6.0 vs 3.5 -> over


def results(c):
    return {(r["employee_id"], r["date"]): r["result"] for r in c.db["h_reco"].find()}


# ── roles ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("user", ["JHS9101", "JHS9001"])     # an employee and a (non-admin) manager
def test_only_admin_can_upload_or_list(api, user):
    _user["id"] = user
    assert upload(api, "/hrms/upload/preview").status_code == 403
    assert upload(api, "/hrms/upload/commit").status_code == 403
    assert api.get("/hrms/uploads").status_code == 403
    assert api.db["h_hrms"].count_documents({}) == 0 and api.db["h_uploads"].count_documents({}) == 0


def test_access_flags(api):
    assert api.get("/hrms/access").json() == {"is_admin": True, "is_manager": True}   # JHS9000 manages 9001/9002
    _user["id"] = "JHS9101"
    assert api.get("/hrms/access").json() == {"is_admin": False, "is_manager": False}
    _user["id"] = "JHS9001"
    assert api.get("/hrms/access").json() == {"is_admin": False, "is_manager": True}


# ── preview / commit ─────────────────────────────────────────────────────────

def test_preview_reports_and_writes_nothing(api):
    r = upload(api, "/hrms/upload/preview").json()
    assert (r["total_rows"], r["valid_rows"], r["error_count"], r["employees"]) == (15, 15, 0, 3)
    assert r["unknown_employees"] == 0
    api.db["h_employees"].delete_one({"EmpID": "JHS9103"})
    r = upload(api, "/hrms/upload/preview").json()
    assert r["unknown_employees"] == 1 and any("not in Employee_details" in w for w in r["warnings"])
    assert (r["date_from"], r["date_to"]) == ("2026-10-02", "2026-10-14")
    assert api.db["h_hrms"].count_documents({}) == 0 and api.db["h_uploads"].count_documents({}) == 0


def test_bad_files_rejected(api):
    assert upload(api, "/hrms/upload/preview", b"hello", "x.txt").status_code == 400
    assert upload(api, "/hrms/upload/preview", b"x" * (10 * 1024 * 1024 + 5), "x.xlsx").status_code == 413
    bad = sample.build_bytes([], [h for h in sample.HEADERS if h != "Date"])
    assert upload(api, "/hrms/upload/commit", bad).status_code == 400
    assert api.db["h_hrms"].count_documents({}) == 0


def test_commit_imports_records_upload_and_derives_holidays(api):
    r = upload(api, "/hrms/upload/commit").json()
    assert r["rows_imported"] == 15 and r["rows_new"] == 15 and r["holidays_added"] == ["2026-10-02"]
    assert api.db["h_hrms"].count_documents({}) == 15
    up = api.db["h_uploads"].find_one()
    assert up["uploaded_by"] == "JHS9000" and up["rows_imported"] == 15 and up["file_name"] == "hrms.xlsx"
    assert api.db["h_config"].find_one({"_id": "timesheet"})["holidays"] == ["2026-10-02"]   # WEO is not a holiday
    doc = api.db["h_hrms"].find_one({"employee_id": "JHS9101", "date": "2026-10-13"})
    assert doc["net_hours"] == 9.25 and "employee_name" not in doc




def test_reupload_is_idempotent(api):
    seed_entries(api)
    same_file = sample.build_bytes()          # build once: workbooks embed a timestamp, so rebuilding changes the hash
    upload(api, "/hrms/upload/commit", same_file)
    snap = lambda: (api.db["h_hrms"].count_documents({}), api.db["h_reco"].count_documents({}),
                    api.db["h_entries"].count_documents({}), results(api),
                    sorted(e["hours"] for e in api.db["h_entries"].find()))
    first = snap()
    r = upload(api, "/hrms/upload/commit", same_file).json()
    assert r["rows_new"] == 0 and r["rows_existing"] == 15
    assert snap() == first
    assert api.db["h_uploads"].count_documents({}) == 2           # each import is still logged
    assert upload(api, "/hrms/upload/preview", same_file).json()["already_imported"] is True










# ── reco view ────────────────────────────────────────────────────────────────

def _view(api, **extra):
    q = "&".join(f"{k}={v}" for k, v in extra.items())
    return api.get(f"/hrms/reco?from=2026-10-01&to=2026-10-31&{q}")








def test_awaiting_dates_listing(api):
    upload(api, "/hrms/upload/commit")
    body = api.get("/hrms/uploads").json()
    awaiting = body["awaiting_dates"]
    assert "2026-10-15" in awaiting and "2026-10-16" in awaiting      # no HRMS rows yet
    assert "2026-10-14" not in awaiting and "2026-10-02" not in awaiting
    assert "2026-10-10" not in awaiting                               # Saturday
    assert body["last_upload"]["date_to"] == "2026-10-14" and len(body["uploads"]) == 1


# ── accept / send back ───────────────────────────────────────────────────────

def _flagged(api):
    seed_entries(api)
    upload(api, "/hrms/upload/commit")







def test_corrected_reupload_updates_the_stored_values(api):
    upload(api, "/hrms/upload/commit")
    fixed = [r if not (r[0] == "JHS9102" and r[1] == "12/10/2026")
             else ("JHS9102", "12/10/2026", "PST", "10:00:00 AM", "03:30:00 PM", "")      # gross 5.5
             for r in sample.ROWS]
    r = upload(api, "/hrms/upload/commit", sample.build_bytes(fixed)).json()
    assert r["rows_new"] == 0 and api.db["h_hrms"].count_documents({}) == 15
    assert api.db["h_hrms"].find_one({"employee_id": "JHS9102", "date": "2026-10-12"})["gross_hours"] == 5.5


def test_upload_never_touches_typed_hours(api):
    seed_entries(api)
    before = sorted((e["employee_id"], e["date"], e["hours"]) for e in api.db["h_entries"].find())
    upload(api, "/hrms/upload/commit")
    assert sorted((e["employee_id"], e["date"], e["hours"]) for e in api.db["h_entries"].find()) == before


def test_failed_import_is_marked_failed(api, monkeypatch):
    with monkeypatch.context() as m:
        m.setattr(hrms_router.store.hrms, "bulk_write", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
        with pytest.raises(RuntimeError):
            upload(api, "/hrms/upload/commit")
    assert api.db["h_uploads"].find_one()["status"] == "failed"
    assert api.get("/hrms/uploads").json()["last_upload"] is None               # a failed upload is not the "last upload"
    upload(api, "/hrms/upload/commit")
    assert api.db["h_uploads"].find_one({"status": "done"}) is not None
