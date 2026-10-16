import os
import socket

import pytest

os.environ.setdefault("MONGO_CONNECTION_STRING", "mongodb://localhost:27018/")

from pymongo import MongoClient

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
