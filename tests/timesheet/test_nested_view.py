"""The read-only nested view (employee > payrolls > 10-day cycles > entries). Scratch Mongo only (Docker, port 27018)."""
import os
import socket
from datetime import datetime

import pytest

os.environ.setdefault("MONGO_CONNECTION_STRING", "mongodb://localhost:27018/")

from pymongo.mongo_client import MongoClient  # the real client: tests/conftest.py swaps pymongo.MongoClient for mongomock

from backend.timesheet import nested_view, rules

PORT = int(os.getenv("MONGO_DEV_PORT", "27018"))


def _up():
    try:
        with socket.create_connection(("127.0.0.1", PORT), timeout=1):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(not _up(), reason="Docker dev Mongo not running")


@pytest.fixture
def vdb():
    db = MongoClient(f"mongodb://127.0.0.1:{PORT}/")["timesnap_test"]
    for c in ("v_entries", "v_reviews", "v_emps", "v_nested"):
        db.drop_collection(c)
    now = datetime.utcnow()

    def e(emp, day, cycle, hours, **kw):
        return {"employee_id": emp, "date": day, "cycle_id": cycle, "hours": hours, "client": "C", "project": "P",
                "project_code": "PL1", "task_id": 1, "task_name": "T", "task_status": "done", "created_at": now, **kw}

    db["v_entries"].insert_many([
        e("JHS1", "2026-09-22", "2026-09-C3", 8),            # 21-30 Sep  -> payroll 2026-10
        e("JHS1", "2026-10-05", "2026-10-C1", 6),            # 1-10 Oct   -> payroll 2026-10
        e("JHS1", "2026-10-05", "2026-10-C1", 2, remarks="second row"),
        e("JHS1", "2026-10-15", "2026-10-C2", 7.5),
        e("JHS1", "2026-10-22", "2026-10-C3", 4),            # 21-31 Oct  -> payroll 2026-11
        e("JHS2", "2026-12-23", "2026-12-C3", 3),            # Dec C3     -> payroll 2027-01
        {"employee_id": "JHS3", "date": "2026-10-05", "hours": 1},   # no cycle id: left out
    ])
    db["v_reviews"].insert_one({"kind": "approval", "employee_id": "JHS1", "cycle_id": "2026-10-C1",
                                "status": "approved", "approved_by": "JHS9001"})
    db["v_emps"].insert_one({"EmpID": "JHS1", "Emp Name": "Emp One", "ReportingEmpName": "Manager A"})
    nested_view.ensure_view(db, "v_nested", "v_entries", "v_reviews", "v_emps")
    yield db
    db.drop_collection("v_nested")


def test_view_nests_employee_payroll_cycle_entries(vdb):
    docs = {d["_id"]: d for d in vdb["v_nested"].find({})}
    assert set(docs) == {"JHS1", "JHS2"}                                           # JHS3 has no cycle id
    one = docs["JHS1"]
    assert one["employee_name"] == "Emp One" and one["reporting_manager"] == "Manager A"
    assert [p["payroll_id"] for p in one["payrolls"]] == ["2026-10", "2026-11"]
    p1 = one["payrolls"][0]
    assert p1["total_hours"] == 23.5 and [c["cycle_id"] for c in p1["cycles"]] == ["2026-09-C3", "2026-10-C1", "2026-10-C2"]
    c1 = p1["cycles"][1]
    assert c1["status"] == "approved" and c1["approved_by"] == "JHS9001" and c1["total_hours"] == 8.0
    assert [x["hours"] for x in c1["entries"]] == [6, 2] and c1["entries"][1]["remarks"] == "second row"
    assert p1["cycles"][0]["status"] == "pending"                                  # no review yet
    assert docs["JHS2"]["payrolls"][0]["payroll_id"] == "2027-01"
    assert docs["JHS2"].get("employee_name") is None


def test_payroll_ids_match_the_python_rule(vdb):
    for d in vdb["v_nested"].find({}):
        for p in d["payrolls"]:
            for c in p["cycles"]:
                assert rules.payroll_id_for_cycle(c["cycle_id"]) == p["payroll_id"]


def test_view_is_read_only_and_the_setup_is_safe(vdb):
    with pytest.raises(Exception):
        vdb["v_nested"].insert_one({"employee_id": "X"})                           # views cannot be written
    assert nested_view.ensure_view(vdb, "v_nested", "v_entries", "v_reviews", "v_emps") == "updated"
    with pytest.raises(RuntimeError):
        nested_view.ensure_view(vdb, "v_entries", "v_entries")                    # never touches a real collection
    with pytest.raises(RuntimeError):
        nested_view.drop_view(vdb, "v_entries")
    assert nested_view.drop_view(vdb, "v_nested") == "dropped" and nested_view.drop_view(vdb, "v_nested") == "absent"
    assert vdb["v_entries"].count_documents({}) == 7                               # source untouched


def test_filtering_one_employee_from_the_view(vdb):
    got = list(vdb["v_nested"].find({"_id": "JHS2"}))
    assert len(got) == 1 and got[0]["payrolls"][0]["cycles"][0]["entries"][0]["hours"] == 3
