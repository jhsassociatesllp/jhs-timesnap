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
from backend.nq import repository
from tests.nq.conftest import dev_settings

CYCLE = "2026-10-C2"
PAYROLL_ID = ObjectId("65f000000000000000000001")
ADMINS = {"JHS9000"}
_user = {"id": "JHS9001"}


@pytest.fixture
def api(cdb, monkeypatch):
    monkeypatch.setattr(cr, "has_admin_module", lambda emp, key: emp in ADMINS and key == "timesheet")
    monkeypatch.setattr(cr, "_today", lambda: date(2026, 10, 21))
    repository.configure(dev_settings())                                  # the fake NQ in Docker, never the real one
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


def test_send_back_is_allowed_before_the_cycle_ends(api, monkeypatch):
    seed(api.db)
    monkeypatch.setattr(cr, "_today", lambda: date(2026, 10, 14))
    assert send(api).status_code == 200


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


def test_review_detail_shows_tasks_against_allotted_hours_and_both_remarks(api):
    seed(api.db)
    api.db["c_entries"].update_one({"employee_id": "JHS9101", "date": "2026-10-12"}, {"$set": {"extra_remarks": "waiting for client data"}})
    body = api.get(f"/timesheet/v2/cycles/{CYCLE}/employee/JHS9101").json()
    by_name = {t["task_name"]: t for t in body["tasks"]}
    planned = next(t for t in body["tasks"] if t["task_id"] == 1)
    assert planned["cycle_hours"] == 17.0 and planned["rows"] == 2 and planned["hours_so_far"] == 17.0
    assert planned["allotted_hours"] == 178.5 and planned["pct_used"] == 10 and planned["over_allotted"] is False   # 21 working days x 8.5
    assert planned["task_start"] == "2026-10-01" and body["nq_unavailable"] is False
    first = next(e for d in body["days"] for e in d["entries"] if e["task_id"] == 1)
    assert first["allotted_days"] == 21 and first["task_end"] == "2026-10-31"
    unplanned = next(t for t in body["tasks"] if t["task_id"] is None)
    assert unplanned["cycle_hours"] == 1.0 and unplanned["allotted_hours"] is None
    day12 = next(d for d in body["days"] if d["date"] == "2026-10-12")
    assert day12["entries"][0]["remarks"] == "did it" and day12["entries"][0]["extra_remarks"] == "waiting for client data"
    assert by_name


def test_over_allotted_is_flagged_and_nq_outage_is_reported(api):
    seed(api.db)
    api.db["c_entries"].insert_one(entry("JHS9101", "2026-10-14", 200, task_id=1))
    body = api.get(f"/timesheet/v2/cycles/{CYCLE}/employee/JHS9101").json()
    assert next(t for t in body["tasks"] if t["task_id"] == 1)["over_allotted"] is True
    from tests.nq.conftest import dev_settings as ds
    repository.configure(ds(port=1, connect_timeout=1))
    from backend.nq import cache
    cache.clear()
    body = api.get(f"/timesheet/v2/cycles/{CYCLE}/employee/JHS9101").json()
    assert body["nq_unavailable"] is True and next(t for t in body["tasks"] if t["task_id"] == 1)["allotted_hours"] is None
    repository.configure(ds())


def test_approve_can_carry_a_remark(api):
    seed(api.db)
    r = api.post(f"/timesheet/v2/cycles/{CYCLE}/approve", json={"employee_ids": ["JHS9101"], "confirm_warnings": True, "note": "Good work"})
    assert r.status_code == 200
    hist = api.db["c_reviews"].find_one({"employee_id": "JHS9101"})["history"]
    assert hist[-1]["action"] == "approved" and hist[-1]["note"] == "Good work"


def test_review_table_verdicts_per_date_and_task(api):
    seed(api.db)                                                         # task 1: two done rows (8.5 + 8.5), plus 1 h unplanned
    api.db["c_entries"].insert_one(entry("JHS9101", "2026-10-15", 6, task_id=2, task_status="in_progress"))   # open task, within
    api.db["c_entries"].insert_one(entry("JHS9101", "2026-10-16", 300, task_id=3, task_status="done"))        # done but far over
    body = api.get(f"/timesheet/v2/cycles/{CYCLE}/employee/JHS9101").json()
    rows = [e for d in body["days"] for e in d["entries"]]
    by_task = {}
    for e in rows:
        by_task.setdefault(e["task_id"], []).append(e)
    first, second = by_task[1][0], by_task[1][1]
    assert first["verdict"] == second["verdict"] == "completed_within" and second["total_on_task"] >= first["total_on_task"]
    assert by_task[2][0]["verdict"] == "in_progress_within"
    assert by_task[3][0]["verdict"] == "completed_over" and by_task[3][0]["total_on_task"] == 300.0
    assert by_task[None][0]["verdict"] == "unplanned"
    s = body["summary"]
    assert (s["completed_within"], s["completed_over"], s["in_progress_within"], s["unplanned"]) == (1, 1, 1, 1)
    assert body["rules"] == {"standard_hours": 8.5, "week_off_days": [5, 6], "lunch_hours": 0.5, "tolerance_hours": 0.5}


def test_allotted_hours_follow_the_admins_week_off_days_and_hours_per_day(api):
    seed(api.db)
    task = lambda: next(t for t in api.get(f"/timesheet/v2/cycles/{CYCLE}/employee/JHS9101").json()["tasks"] if t["task_id"] == 1)
    assert task()["allotted_hours"] == 178.5                                     # Oct 1-31: 21 working days (Sat/Sun off, 2 Oct holiday) x 8.5
    api.db["c_config"].update_one({"_id": "timesheet"}, {"$set": {"week_off_days": [6], "standard_hours": 8}})
    assert task()["allotted_hours"] == 26 * 8.0                                  # only Sunday off: 27 days minus the holiday = 26 x 8


def test_review_shows_hrms_hours_against_typed_hours_per_date(api):
    seed(api.db)                                                           # typed: 12th 8.5, 13th 9.5 (8.5 + 1 unplanned), 14th day off
    hr = lambda day, **kw: api.db["c_hrms"].insert_one({"employee_id": "JHS9101", "date": day, "kind": "working", "status_code": "PST", **kw})
    hr("2026-10-12", gross_hours=9.0, in_time="09:30", out_time="18:30")        # net 8.5 -> typed 8.5 matched
    hr("2026-10-13", gross_hours=8.0, in_time="10:00", out_time="18:00")        # net 7.5 -> typed 9.5 over by 2
    hr("2026-10-15", gross_hours=9.0, in_time="09:30", out_time="18:30")        # punch but nothing typed -> not filled
    hr("2026-10-16", gross_hours=None)                                           # present, no punch, nothing typed -> nothing expected
    api.db["c_hrms"].insert_one({"employee_id": "JHS9101", "date": "2026-10-14", "kind": "leave", "status_code": "CL", "leave_flag": True})
    api.db["c_entries"].insert_one(entry("JHS9101", "2026-10-17", 3))            # typed on a Saturday, no HRMS row at all
    body = api.get(f"/timesheet/v2/cycles/{CYCLE}/employee/JHS9101").json()
    by = {d["date"]: d["hrms"] for d in body["days"]}
    assert by["2026-10-12"]["result"] == "matched" and by["2026-10-12"]["diff"] == 0.0 and by["2026-10-12"]["net_hours"] == 8.5
    assert by["2026-10-13"]["result"] == "over" and by["2026-10-13"]["diff"] == 2.0 and by["2026-10-13"]["typed_hours"] == 9.5
    assert by["2026-10-14"]["result"] == "leave" and by["2026-10-15"]["result"] == "not_filled"
    assert by["2026-10-16"]["result"] is None and by["2026-10-17"] == {"has_data": False}
    assert (by["2026-10-12"]["in_time"], by["2026-10-12"]["out_time"]) == ("09:30", "18:30")
    s = body["hrms_summary"]
    assert (s["matched"], s["over"], s["not_filled"], s["leave"]) == (1, 1, 1, 1) and s["has_data"] is True
    assert (s["hrms_hours"], s["typed_hours"], s["diff_hours"]) == (24.5, 18.0, -6.5)             # 8.5 + 7.5 + 8.5 net; typed 8.5 + 9.5 + 0
    team = next(r for r in api.get(f"/timesheet/v2/cycles/{CYCLE}/team").json()["rows"] if r["employee_id"] == "JHS9101")
    assert team["hrms_hours"] == 24.5 and team["diff_hours"] == -6.5 and team["reco_gaps"] == 2
    assert any("differ from HRMS" in w for w in team["warnings"])


def test_lunch_and_tolerance_come_from_the_admin_settings(api):
    seed(api.db)
    api.db["c_hrms"].insert_one({"employee_id": "JHS9101", "date": "2026-10-12", "kind": "working", "gross_hours": 9.0})
    day = lambda: next(d for d in api.get(f"/timesheet/v2/cycles/{CYCLE}/employee/JHS9101").json()["days"] if d["date"] == "2026-10-12")["hrms"]
    assert day()["net_hours"] == 8.5 and day()["result"] == "matched"
    api.db["c_config"].update_one({"_id": "timesheet"}, {"$set": {"lunch_hours": 1.5, "tolerance_hours": 0.25}})
    assert day()["net_hours"] == 7.5 and day()["result"] == "over"                  # typed 8.5 vs net 7.5, outside 0.25
    api.db["c_config"].update_one({"_id": "timesheet"}, {"$set": {"tolerance_hours": 1.0}})
    assert day()["result"] == "matched"
