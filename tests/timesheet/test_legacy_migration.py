import os
import socket

import pytest

os.environ.setdefault("MONGO_CONNECTION_STRING", "mongodb://localhost:27018/")

from pymongo.mongo_client import MongoClient  # the real client: tests/conftest.py swaps pymongo.MongoClient for mongomock

from backend.timesheet.legacy_migration import convert, migrate

PORT = int(os.getenv("MONGO_DEV_PORT", "27018"))

LEGACY = {
    "employeeId": "jhs9101",
    "payrolls": [
        {"cycle_id": "c1", "approval_status": "approved", "entries": [
            {"id": "a1", "date": "2026-10-12", "client": "Acme", "project": "Audit", "projectCode": "PL1",
             "activity": "Fieldwork", "projectHours": "7.5", "projectStartTime": "09:00"},
            {"id": "a2", "date": "2026-10-13", "location": "Leave", "projectHours": ""},      # no hours: skipped
        ]},
        {"cycle_id": "c2", "weeks": [{"entries": [                                            # oldest nested shape
            {"date": "2026-10-21", "client": "B", "project": "P", "projectCode": "PL2",
             "activity": "x", "projectHours": "8"}]}]},
    ],
}


def test_convert_maps_fields_and_skips_hourless_rows():
    rows = list(convert(LEGACY))
    assert len(rows) == 2
    a, b = rows
    assert (a["employee_id"], a["date"], a["hours"], a["project_code"], a["cycle_id"]) == \
           ("JHS9101", "2026-10-12", 7.5, "PL1", "2026-10-C2")
    assert a["approved"] is True and a["legacy"] is True and a["task_id"] is None
    assert (a["location"], a["remarks"], a["task_name"], a["reporting_manager_name"]) == ("", "", "Fieldwork", "")
    assert b["cycle_id"] == "2026-10-C3" and b["approved"] is False and b["legacy_id"].startswith("h_")


def _mongo_up():
    s = socket.socket()
    s.settimeout(1)
    try:
        return s.connect_ex(("127.0.0.1", PORT)) == 0
    finally:
        s.close()


@pytest.mark.skipif(not _mongo_up(), reason="dev Mongo not running")
def test_migrate_is_idempotent_dry_run_writes_nothing_and_source_untouched():
    db = MongoClient(f"mongodb://127.0.0.1:{PORT}/")["timesnap_test"]
    db["mig_src"].drop()
    db["mig_dst"].drop()
    db["mig_src"].insert_one(dict(LEGACY))
    before = db["mig_src"].find_one({"employeeId": "jhs9101"})

    dry = migrate(db["mig_src"], db["mig_dst"], apply=False)
    assert dry["inserted"] == 2 and db["mig_dst"].count_documents({}) == 0

    first = migrate(db["mig_src"], db["mig_dst"], apply=True)
    second = migrate(db["mig_src"], db["mig_dst"], apply=True)
    assert first["inserted"] == 2 and second["inserted"] == 0 and second["already_present"] == 2
    assert db["mig_dst"].count_documents({}) == 2
    assert db["mig_src"].find_one({"employeeId": "jhs9101"}) == before            # original untouched


@pytest.mark.skipif(not _mongo_up(), reason="dev Mongo not running")
def test_submitted_days_and_employee_filter():
    db = MongoClient(f"mongodb://127.0.0.1:{PORT}/")["timesnap_test"]
    for c in ("mig_src2", "mig_dst2", "mig_sub2"):
        db[c].drop()
    legacy = {"employeeId": "JHS9101", "payrolls": [
        {"cycle_id": "c1", "submitted": True, "entries": [
            {"id": "a1", "date": "2026-10-12", "location": "Client Site", "client": "Acme", "project": "Audit",
             "projectCode": "PL1", "activity": "Fieldwork", "remarks": "Tested POs", "projectHours": "7.5",
             "reportingManagerEntry": "Mgr"},
            {"id": "a2", "date": "2026-10-13", "location": "Leave", "projectHours": ""}]},
        {"cycle_id": "c2", "submitted": False, "entries": [{"id": "z", "date": "2026-10-20", "projectHours": "8"}]}]}
    other = {"employeeId": "JHS9999", "payrolls": [{"submitted": True, "entries": [{"id": "q", "date": "2026-10-12", "projectHours": "8"}]}]}
    db["mig_src2"].insert_many([legacy, other])
    dry = migrate(db["mig_src2"], db["mig_dst2"], apply=False, submissions=db["mig_sub2"], employees=["jhs9101"])
    assert dry["employees"] == 1 and dry["inserted"] == 2 and dry["days_submitted"] == 2
    assert db["mig_dst2"].count_documents({}) == 0 and db["mig_sub2"].count_documents({}) == 0
    migrate(db["mig_src2"], db["mig_dst2"], apply=True, submissions=db["mig_sub2"], employees=["JHS9101"])
    again = migrate(db["mig_src2"], db["mig_dst2"], apply=True, submissions=db["mig_sub2"], employees=["JHS9101"])
    assert again["inserted"] == 0 and again["days_submitted"] == 0                                   # idempotent
    e = db["mig_dst2"].find_one({"legacy_id": "a1"})
    assert (e["location"], e["remarks"], e["task_name"], e["reporting_manager_name"]) == ("Client Site", "Tested POs", "Fieldwork", "Mgr")
    subs = {s["date"]: s["location"] for s in db["mig_sub2"].find()}
    assert subs == {"2026-10-12": "Client Site", "2026-10-13": "Leave"}                              # draft payroll + other employee ignored
    assert db["mig_dst2"].count_documents({"employee_id": "JHS9999"}) == 0
