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
    db["h_config"].insert_one({"_id": "timesheet", "pilot_employees": ["JHS9101", "JHS9102", "JHS9103"]})
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


def test_reco_outcomes_for_typed_hours(api):
    seed_entries(api)
    upload(api, "/hrms/upload/commit")
    got = results(api)
    assert got[("JHS9101", "2026-10-12")] == "matched"
    assert got[("JHS9101", "2026-10-13")] == "matched"          # typed 9.25 vs HRMS net 9.25
    assert got[("JHS9101", "2026-10-14")] == "not_filled"
    assert got[("JHS9102", "2026-10-12")] == "short"
    assert got[("JHS9102", "2026-10-13")] == "leave"
    assert got[("JHS9102", "2026-10-14")] == "no_punch"
    assert ("JHS9103", "2026-10-13") not in got                  # absent and nothing filled
    assert got[("JHS9103", "2026-10-14")] == "over"
    assert all(got[(e, "2026-10-02")] == "leave" for e in ("JHS9101", "JHS9102", "JHS9103"))
    typed = api.db["h_entries"].find_one({"employee_id": "JHS9101", "date": "2026-10-13"})
    assert typed["hours"] == 9.25


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


def test_corrected_reupload_updates_values_and_reco(api):
    seed_entries(api)
    upload(api, "/hrms/upload/commit")
    fixed = [r if not (r[0] == "JHS9102" and r[1] == "12/10/2026")
             else ("JHS9102", "12/10/2026", "PST", "10:00:00 AM", "03:30:00 PM", "")      # gross 5.5 net 5.0
             for r in sample.ROWS]
    r = upload(api, "/hrms/upload/commit", sample.build_bytes(fixed)).json()
    assert r["rows_new"] == 0
    assert results(api)[("JHS9102", "2026-10-12")] == "matched"                          # 5.0 vs 5.0
    assert api.db["h_hrms"].count_documents({}) == 15


def test_upload_never_changes_typed_hours(api):
    """HRMS is only compared with what the employee typed - even on a one-entry day, locked or not."""
    api.db["h_entries"].insert_many([
        entry("JHS9103", "2026-10-12", 6),                                      # HRMS net is 8.5 that day
        entry("JHS9101", "2026-10-13", 2, approved=True, locked=True),
        entry("JHS9101", "2026-10-14", 2), entry("JHS9101", "2026-10-14", 3)])
    upload(api, "/hrms/upload/commit")
    hours = {(e["employee_id"], e["date"], i): e["hours"] for i, e in enumerate(api.db["h_entries"].find())}
    assert sorted(hours.values()) == [2, 2, 3, 6]                              # nothing was filled or corrected
    assert results(api)[("JHS9103", "2026-10-12")] == "short"                  # ...it is just reported as short


def test_non_pilot_employees_get_no_reco(api):
    api.db["h_config"].update_one({"_id": "timesheet"}, {"$set": {"pilot_employees": ["JHS9101"]}})
    upload(api, "/hrms/upload/commit")
    assert {e for e, _ in results(api)} == {"JHS9101"}
    assert api.db["h_hrms"].count_documents({}) == 15             # attendance is still stored for everyone


def test_failed_import_is_marked_failed_and_managers_see_no_file_details(api, monkeypatch):
    with monkeypatch.context() as m:
        m.setattr(reco, "recompute_range", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
        with pytest.raises(RuntimeError):
            upload(api, "/hrms/upload/commit")
    assert api.db["h_uploads"].find_one()["status"] == "failed"
    assert api.get("/hrms/uploads").json()["last_upload"] is None               # a failed upload is not the "last upload"
    upload(api, "/hrms/upload/commit")
    assert api.db["h_uploads"].find_one({"status": "done"}) is not None
    _user["id"] = "JHS9001"
    lu = _view(api).json()["last_upload"]
    assert set(lu) == {"uploaded_at", "date_from", "date_to"}                    # no file name / uploader for managers


# ── reco view ────────────────────────────────────────────────────────────────

def _view(api, **extra):
    q = "&".join(f"{k}={v}" for k, v in extra.items())
    return api.get(f"/hrms/reco?from=2026-10-01&to=2026-10-31&{q}")


def test_manager_sees_only_own_reportees(api):
    seed_entries(api)
    upload(api, "/hrms/upload/commit")
    _user["id"] = "JHS9001"
    rows = _view(api).json()["rows"]
    assert {r["employee_id"] for r in rows} == {"JHS9101", "JHS9102"}
    _user["id"] = "JHS9002"
    assert {r["employee_id"] for r in _view(api).json()["rows"]} == {"JHS9103"}
    _user["id"] = "JHS9001"
    assert {r["employee_id"] for r in _view(api, manager="JHS9002").json()["rows"]} == {"JHS9101", "JHS9102"}  # filter ignored


def test_admin_sees_all_and_can_filter_by_team(api):
    seed_entries(api)
    upload(api, "/hrms/upload/commit")
    body = _view(api).json()
    assert {r["employee_id"] for r in body["rows"]} == {"JHS9101", "JHS9102", "JHS9103"}
    assert body["summary"]["short"] == 1 and body["summary"]["over"] == 1 and body["summary"]["no_punch"] == 1
    assert {r["employee_id"] for r in _view(api, manager="JHS9002").json()["rows"]} == {"JHS9103"}
    assert body["last_upload"]["file_name"] == "hrms.xlsx"


def test_employee_cannot_view_reco_and_range_is_limited(api):
    _user["id"] = "JHS9101"
    assert _view(api).status_code == 403
    _user["id"] = "JHS9000"
    assert api.get("/hrms/reco?from=2026-01-01&to=2026-12-31").status_code == 400
    assert api.get("/hrms/reco?from=bad&to=2026-12-31").status_code == 400


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


def test_review_permissions(api):
    _flagged(api)
    url = "/hrms/reco/JHS9102/2026-10-12/send-back"
    _user["id"] = "JHS9002"                                             # someone else's manager
    assert api.post(url, json={"note": "x"}).status_code == 403
    _user["id"] = "JHS9102"                                             # the employee themself
    assert api.post("/hrms/reco/JHS9102/2026-10-12/accept", json={}).status_code == 403
    _user["id"] = "JHS9001"                                             # their manager
    r = api.post(url, json={"note": "Add the missing 2h"})
    assert r.status_code == 200 and r.json()["status"] == "sent_back"
    assert api.db["h_reco"].find_one({"employee_id": "JHS9102", "date": "2026-10-12"})["manager_note"] == "Add the missing 2h"
    _user["id"] = "JHS9000"                                             # admin may review anyone
    assert api.post("/hrms/reco/JHS9103/2026-10-14/accept", json={}).json()["status"] == "accepted"


def test_review_validation(api):
    _flagged(api)
    _user["id"] = "JHS9001"
    assert api.post("/hrms/reco/JHS9102/2026-10-12/send-back", json={"note": " "}).status_code == 422
    assert api.post("/hrms/reco/JHS9101/2026-10-12/accept", json={}).status_code == 422       # matched: nothing to review
    assert api.post("/hrms/reco/JHS9101/2026-10-09/accept", json={}).status_code == 404
    assert api.post("/hrms/reco/JHS9101/not-a-date/accept", json={}).status_code == 400
    assert api.post("/hrms/reco/JHS9102/2026-10-12/accept", json={"note": "n" * 501}).status_code == 422


def test_employee_edit_reopens_a_sent_back_day(api):
    _flagged(api)
    _user["id"] = "JHS9001"
    api.post("/hrms/reco/JHS9102/2026-10-12/send-back", json={"note": "fix"})
    api.db["h_entries"].insert_one(entry("JHS9102", "2026-10-12", 2))          # employee adds 2h -> 7.0 vs 7.0
    reco.safe_recompute_day("JHS9102", "2026-10-12")
    row = api.db["h_reco"].find_one({"employee_id": "JHS9102", "date": "2026-10-12"})
    assert row["result"] == "matched" and row["status"] == "open" and row["manager_note"] == "fix"
