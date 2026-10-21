"""
Step 4: send-back, review detail and the mirror of approved cycles into the classic Timesheet_data.
Scratch Mongo only (see conftest). 'Today' is 2026-10-21; cycle 2026-10-C2 (11-20 Oct) has ended.
The classic payroll cycle used here is 21 Sep - 20 Oct, i.e. the 10-day cycles 2026-09-C3, 2026-10-C1, 2026-10-C2.
"""
from datetime import date, datetime

import pytest
from bson import ObjectId
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.auth import get_current_user
from backend.cycle import mirror, router as cr
from backend.cycle.locks import cycle_locked, cycle_reopened
from backend.cycle.store import store
from backend.timesheet import rules
from tests.cycle.conftest import entry
from tests.cycle.test_cycle_api import fill_cycle

CYCLE = "2026-10-C2"
PAYROLL_ID = ObjectId("65f000000000000000000001")
ADMINS = {"JHS9000"}
_user = {"id": "JHS9001"}


@pytest.fixture
def api(cdb, monkeypatch):
    monkeypatch.setattr(cr, "has_admin_module", lambda emp, key: emp in ADMINS and key == "timesheet")
    monkeypatch.setattr(cr, "_today", lambda: date(2026, 10, 21))
    cdb["c_pcycles"].insert_one({"_id": PAYROLL_ID, "cycle_label": "Sep-Oct 2026",
                                 "start_date": "2026-09-21", "end_date": "2026-10-20"})
    app = FastAPI()
    app.include_router(cr.router)
    app.dependency_overrides[get_current_user] = lambda: _user["id"]
    _user["id"] = "JHS9001"
    c = TestClient(app)
    c.db = cdb
    return c


def seed(db, emp="JHS9101"):
    now = datetime.utcnow()
    for day in ("2026-10-12", "2026-10-13"):
        db["c_submissions"].insert_one({"employee_id": emp, "date": day, "cycle_id": CYCLE, "submitted_at": now,
                                        "location": "Office"})
        db["c_entries"].insert_one(entry(emp, day, 8.5, client="Client A", project="Audit", location="Office",
                                         remarks="did it", reporting_manager_name="Manager A"))
    db["c_entries"].insert_one(entry(emp, "2026-10-13", 1, is_unplanned=True, task_id=None, task_name="",
                                     remarks="urgent call", location="Office"))
    fill_cycle(db, emp)
    db["c_submissions"].update_many({"employee_id": emp}, {"$set": {"cycle_id": CYCLE}})
    # a day off, submitted without rows
    db["c_submissions"].update_one({"employee_id": emp, "date": "2026-10-14"}, {"$set": {"location": "Leave"}})


def classic_doc(db, emp="JHS9101"):
    return db["c_legacy"].find_one({"employeeId": emp})


def payroll(db, emp="JHS9101"):
    return next(p for p in classic_doc(db, emp)["payrolls"] if p["cycle_id"] == str(PAYROLL_ID))


def approve(api, emp="JHS9101"):
    return api.post(f"/timesheet/v2/cycles/{CYCLE}/approve", json={"employee_ids": [emp], "confirm_warnings": True})


# ── mirror ───────────────────────────────────────────────────────────────────

def test_approve_mirrors_rows_but_payroll_stays_pending_until_all_cycles_approved(api):
    seed(api.db)
    r = approve(api)
    assert r.status_code == 200 and r.json()["mirror_failed"] == []
    p = payroll(api.db)
    mirrored = [e for e in p["entries"] if e.get("v2_mirror")]
    assert len(mirrored) == 4 and all(e["v2_cycle_id"] == CYCLE for e in mirrored)
    work = [e for e in mirrored if e["projectCode"]]
    assert {e["projectHours"] for e in work} == {"8.5", "1"} or len(work) == 3
    assert any(e["activityOther"] and e["activityReason"] == "urgent call" for e in mirrored)
    off = [e for e in mirrored if e["location"] == "Leave"]
    assert len(off) == 1 and off[0]["projectHours"] == "" and off[0]["date"] == "2026-10-14"
    assert p["approval_status"] is None and p["totalHours"] == 18.0     # 8.5 + 8.5 + 1
    assert api.db["c_approved"].count_documents({}) == 0                # classic "approved" list untouched
    assert api.db["c_reviews"].find_one({"employee_id": "JHS9101"})["mirror"]["status"] == "ok"


def test_payroll_approved_when_every_cycle_in_it_is_approved(api):
    seed(api.db)
    for cid in ("2026-09-C3", "2026-10-C1"):
        api.db["c_reviews"].insert_one({"kind": "approval", "employee_id": "JHS9101", "cycle_id": cid, "status": "approved"})
    assert approve(api).status_code == 200
    p = payroll(api.db)
    assert p["approval_status"] == "approved" and p["approved_by"] == "JHS9001"
    assert api.db["c_approved"].find_one({"ReportingEmpCode": "JHS9001"})["EmployeesCodes"] == ["JHS9101"]
    assert api.db["c_apphist"].count_documents({"employeeId": "JHS9101", "action": "approved"}) == 1


def test_mirror_merges_never_replaces_classic_rows_and_is_idempotent(api):
    seed(api.db)
    api.db["c_legacy"].insert_one({"employeeId": "JHS9101", "employeeName": "Emp One", "payrolls": [
        {"cycle_id": str(PAYROLL_ID), "submitted": True, "submitted_at": "2026-10-01T00:00:00",
         "entries": [{"id": "old1", "date": "2026-09-25", "projectCode": "PL-OLD", "projectHours": "7"}],
         "approval_status": None}, {"cycle_id": "other", "entries": [{"id": "x"}]}]})
    approve(api)
    first = payroll(api.db)["entries"]
    cyc = rules.cycle_from_id(CYCLE)
    mirror.write("JHS9101", cyc, "JHS9001")
    mirror.write("JHS9101", cyc, "JHS9001")
    again = payroll(api.db)["entries"]
    assert len(again) == len(first) == 5                                              # 1 classic + 4 mirrored, no duplicates
    assert again[0]["id"] == "old1" or any(e["id"] == "old1" for e in again)
    assert any(p["cycle_id"] == "other" for p in classic_doc(api.db)["payrolls"])     # other payrolls untouched
    assert api.db["c_legacy"].count_documents({}) == 1


def test_unlock_removes_only_mirrored_rows_of_that_cycle(api):
    seed(api.db)
    api.db["c_legacy"].insert_one({"employeeId": "JHS9101", "payrolls": [
        {"cycle_id": str(PAYROLL_ID), "submitted": True, "entries": [{"id": "old1", "date": "2026-09-25", "projectHours": "7"}]}]})
    api.db["c_reviews"].insert_many([{"kind": "approval", "employee_id": "JHS9101", "cycle_id": c, "status": "approved"}
                                     for c in ("2026-09-C3", "2026-10-C1")])
    approve(api)
    assert payroll(api.db)["approval_status"] == "approved"
    _user["id"] = "JHS9000"
    r = api.post(f"/timesheet/v2/cycles/{CYCLE}/unlock", json={"employee_id": "JHS9101", "reason": "Fix the 13th"})
    assert r.status_code == 200
    p = payroll(api.db)
    assert [e["id"] for e in p["entries"]] == ["old1"] and p["approval_status"] is None
    assert api.db["c_approved"].find_one({"ReportingEmpCode": "JHS9001"})["EmployeesCodes"] == []
    assert not cycle_locked("JHS9101", CYCLE) and cycle_reopened("JHS9101", CYCLE)


def test_approval_survives_missing_payroll_cycle_and_is_recorded(api):
    seed(api.db)
    api.db["c_pcycles"].delete_many({})
    r = approve(api)
    assert r.status_code == 200 and r.json()["mirror_failed"] == []
    assert cycle_locked("JHS9101", CYCLE) and classic_doc(api.db) is None
    assert api.db["c_reviews"].find_one({"employee_id": "JHS9101"})["mirror"]["status"] == "no_payroll_cycle"


def test_failed_mirror_keeps_the_approval_and_admin_can_rerun(api, monkeypatch):
    seed(api.db)
    real_write = mirror.write
    monkeypatch.setattr(mirror, "write", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db down")))
    r = approve(api)
    assert r.status_code == 200 and r.json()["mirror_failed"] == ["JHS9101"]
    assert cycle_locked("JHS9101", CYCLE)
    assert api.db["c_reviews"].find_one({"employee_id": "JHS9101"})["mirror"]["status"] == "error"
    monkeypatch.setattr(mirror, "write", real_write)
    assert api.post(f"/timesheet/v2/cycles/{CYCLE}/mirror", json={"employee_id": "JHS9101"}).status_code == 403
    _user["id"] = "JHS9000"
    ok = api.post(f"/timesheet/v2/cycles/{CYCLE}/mirror", json={"employee_id": "JHS9101"})
    assert ok.status_code == 200 and ok.json()["status"] == "ok" and payroll(api.db)["entries"]


# ── send back ────────────────────────────────────────────────────────────────

def send(api, emp="JHS9101", note="Please fix the 13th", cycle=CYCLE):
    return api.post(f"/timesheet/v2/cycles/{cycle}/send-back", json={"employee_id": emp, "note": note})


def test_send_back_reopens_with_note_and_shows_on_team_row(api):
    seed(api.db)
    assert send(api).status_code == 200
    assert cycle_reopened("JHS9101", CYCLE) and not cycle_locked("JHS9101", CYCLE)
    row = next(r for r in api.get(f"/timesheet/v2/cycles/{CYCLE}/team").json()["rows"] if r["employee_id"] == "JHS9101")
    assert row["status"] == "sent_back" and row["note"] == "Please fix the 13th" and row["resubmitted"] is False
    api.db["c_submissions"].update_one({"employee_id": "JHS9101", "date": "2026-10-13"},
                                       {"$set": {"submitted_at": datetime.utcnow()}})
    row = next(r for r in api.get(f"/timesheet/v2/cycles/{CYCLE}/team").json()["rows"] if r["employee_id"] == "JHS9101")
    assert row["resubmitted"] is True
    assert approve(api).status_code == 200                                # a sent-back cycle can still be approved
    review = api.db["c_reviews"].find_one({"employee_id": "JHS9101"})
    assert review["status"] == "approved" and "note" not in review
    assert [h["action"] for h in review["history"]] == ["sent_back", "approved"]


def test_send_back_rules(api):
    seed(api.db)
    assert send(api, note="x").status_code == 422                          # note required (3+ chars)
    assert send(api, emp="JHS9103").status_code == 403                     # not their reportee
    assert send(api, emp="JHS9104").status_code == 422                     # not on the daily timesheet
    _user["id"] = "JHS9101"
    assert send(api).status_code == 403                                    # an employee
    _user["id"] = "JHS9001"
    approve(api)
    assert send(api).status_code == 409                                    # approved: admin must unlock first
    _user["id"] = "JHS9000"
    assert send(api, emp="JHS9103").status_code in (200, 422)              # admin may send back anyone (pilot only)


def test_send_back_before_cycle_end_refused(api, monkeypatch):
    seed(api.db)
    monkeypatch.setattr(cr, "_today", lambda: date(2026, 10, 14))
    assert send(api).status_code == 422
    assert api.db["c_reviews"].count_documents({}) == 0


# ── review detail ────────────────────────────────────────────────────────────

def test_employee_detail_rows_and_roles(api):
    seed(api.db)
    r = api.get(f"/timesheet/v2/cycles/{CYCLE}/employee/jhs9101")
    assert r.status_code == 200
    body = r.json()
    day13 = next(d for d in body["days"] if d["date"] == "2026-10-13")
    assert day13["hours"] == 9.5 and day13["state"] == "submitted"
    assert any(e["is_unplanned"] and e["remarks"] == "urgent call" for e in day13["entries"])
    assert next(d for d in body["days"] if d["date"] == "2026-10-14")["location"] == "Leave"
    assert body["employee"]["employee_id"] == "JHS9101"
    assert api.get(f"/timesheet/v2/cycles/{CYCLE}/employee/JHS9103").status_code == 403
    assert api.get(f"/timesheet/v2/cycles/{CYCLE}/employee/JHS9104").status_code == 422
    _user["id"] = "JHS9101"
    assert api.get(f"/timesheet/v2/cycles/{CYCLE}/employee/JHS9101").status_code == 403
    _user["id"] = "JHS9000"
    assert api.get(f"/timesheet/v2/cycles/{CYCLE}/employee/JHS9101").status_code == 200
    assert api.get("/timesheet/v2/cycles/2026-10-C9/employee/JHS9101").status_code == 400
