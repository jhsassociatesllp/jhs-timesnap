"""
API tests for "My day". They need the Docker dev stack (docker compose -f docker-compose.dev.yml up -d):
MySQL on 3308 (seeded fake NQ) and Mongo on 27018 (scratch database 'timesnap_test'). The clock is pinned to
Friday 2026-10-16 10:00 IST (cycle 2026-10-C2 = 11-20 Oct, deadline 25 Oct 23:59). JHS9101 (NQ user 3) has the
assigned tasks 1, 2, 3 (PL-T001) and 5 (PL-T002) on 2026-10-14; task 13 belongs to someone else, task 4 is finished.
"""
import os
import socket
from datetime import datetime

import pytest

os.environ.setdefault("MONGO_CONNECTION_STRING", "mongodb://localhost:27018/")

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pymongo import MongoClient

from backend.auth import get_current_user
from backend.cycle.store import store as cycle_store
from backend.hrms import reco as hrms_reco
from backend.nq import cache, repository
from backend.timesheet import daily, payrolls
from tests.nq.conftest import DEV_PORT, dev_settings

MONGO_PORT = int(os.getenv("MONGO_DEV_PORT", "27018"))
DAY = "2026-10-14"
NOW = datetime(2026, 10, 16, 10, 0, 0)


def _up(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(
    not (_up(MONGO_PORT) and _up(DEV_PORT)),
    reason="Docker dev stack not running (docker compose -f docker-compose.dev.yml up -d)")

_user = {"id": "JHS9101"}


@pytest.fixture
def api(monkeypatch):
    db = MongoClient(f"mongodb://127.0.0.1:{MONGO_PORT}/")["timesnap_test"]
    for coll in ("entries", "submissions", "drafts", "hrms", "uploads", "reco", "config", "employees", "reviews"):
        db[f"t_{coll}"].drop()
    for attr in ("entries", "submissions", "drafts", "config", "employees"):
        monkeypatch.setattr(daily.store, attr, db[f"t_{attr}"])
    for attr in ("entries", "submissions", "hrms", "uploads", "reco", "config", "employees"):
        monkeypatch.setattr(hrms_reco.store, attr, db[f"t_{attr}"])
    monkeypatch.setattr(cycle_store, "reviews", db["t_reviews"])
    monkeypatch.setattr(cycle_store, "payrolls", db["t_payrolls"])
    db["t_payrolls"].drop()
    for month in ("2026-10", "2026-11"):                                   # the payrolls an admin has created
        db["t_payrolls"].insert_one(payrolls.build_payroll(month, 5, "JHS9000"))
    payrolls.invalidate()
    monkeypatch.setattr(daily, "_now_ist", lambda: NOW)
    db["t_config"].insert_one({"_id": "timesheet", "timesheet_scope": "pilot", "pilot_employees": ["JHS9101", "JHS9102", "JHS1562"],
                               "holidays": ["2026-10-02"]})
    db["t_employees"].insert_many([
        {"EmpID": "JHS9101", "PartnerEmpCode": "JHS02", "ReportingEmpCode": "JHS9001", "ReportingEmpName": "Manager A"},
        {"EmpID": "JHS9102", "PartnerEmpCode": "JHS02", "ReportingEmpCode": "JHS9001", "ReportingEmpName": "Manager A"},
        {"EmpID": "JHS1562", "PartnerEmpCode": "JHS02"},                     # free-text employee, always excluded
    ])
    repository.configure(dev_settings())
    app = FastAPI()
    app.include_router(daily.router)
    app.dependency_overrides[get_current_user] = lambda: _user["id"]
    _user["id"] = "JHS9101"
    c = TestClient(app)
    c.db = db
    yield c
    repository.configure(dev_settings())
    cache.clear()


def row(task_id, hours=None, status="in_progress", remarks="", unplanned=False, **kw):
    return {"task_id": task_id, "hours": hours, "task_status": status, "remarks": remarks, "is_unplanned": unplanned, **kw}


def unplanned(hours=None, remarks=""):
    return row(None, hours, remarks=remarks, unplanned=True)


def put(c, entries, location="Office", emp="JHS9101", day=DAY):
    return c.put(f"/timesheet/v2/day/{emp}/{day}", json={"location": location, "entries": entries})


def submit(c, emp="JHS9101", day=DAY):
    return c.post(f"/timesheet/v2/day/{emp}/{day}/submit")


def get_day(c, emp="JHS9101", day=DAY):
    return c.get(f"/timesheet/v2/day/{emp}?date={day}")


def strip(c, date=None, emp="JHS9101"):
    return c.get(f"/timesheet/v2/cycle-days/{emp}" + (f"?date={date}" if date else ""))


def states(resp):
    return {d["date"]: d["state"] for d in resp.json()["days"]}


# ── roles ────────────────────────────────────────────────────────────────────

def test_cannot_touch_another_employees_day(api):
    assert get_day(api, "JHS9102").status_code == 403
    assert put(api, [row(5, 1)], emp="JHS9102").status_code == 403
    assert submit(api, "JHS9102").status_code == 403
    assert strip(api, emp="JHS9102").status_code == 403
    assert api.get("/timesheet/v2/enabled/JHS9102").status_code == 403


def test_not_in_pilot_is_forbidden_and_free_text_employees_are_excluded(api):
    _user["id"] = "JHS9103"
    assert api.get("/timesheet/v2/enabled/JHS9103").json()["enabled"] is False
    assert get_day(api, "JHS9103").status_code == 403 and strip(api, emp="JHS9103").status_code == 403
    _user["id"] = "JHS1562"
    assert api.get("/timesheet/v2/enabled/JHS1562").json()["enabled"] is False
    assert put(api, [], emp="JHS1562").status_code == 403


# ── reading a day ────────────────────────────────────────────────────────────

def test_day_payload_has_assigned_tasks_budget_and_no_hrms(api):
    b = get_day(api).json()
    assert sorted(t["task_id"] for t in b["tasks"]) == [1, 2, 3, 5]
    t1 = next(t for t in b["tasks"] if t["task_id"] == 1)
    assert t1["budget_hours"] == 21 * 8.5 and t1["project_code"] == "PL-T001" and t1["client_name"] == "Test Client A"
    assert next(t for t in b["tasks"] if t["task_id"] == 3)["is_overdue"] is True
    assert b["date"] == DAY and b["weekday"] == "Wednesday" and b["location"] is None and b["submitted"] is False
    assert b["cycle"]["id"] == "2026-10-C2" and b["cycle"]["deadline"] == "2026-10-25" and b["cycle"]["deadline_passed"] is False
    assert b["reporting_manager"] == {"code": "JHS9001", "name": "Manager A"}
    assert b["totals"] == {"task_hours": 0, "rows": 0, "over_24": False} and b["read_only"] is False
    assert "hrms" not in b and "reco" not in b                                   # no HRMS anywhere on the employee screen


def test_future_and_bad_dates(api):
    assert get_day(api, day="2026-10-17").status_code == 400
    assert get_day(api, day="nope").status_code == 400
    assert put(api, [], day="2026-10-17").status_code == 400


# ── saving a draft ───────────────────────────────────────────────────────────

def test_draft_is_lenient_and_copies_everything_from_nq(api):
    r = put(api, [row(1, None, remarks="Kick-off", client="EVIL", project="EVIL", project_code="EVIL")], location="Client Site")
    assert r.status_code == 200
    b = r.json()
    e = b["entries"][0]
    assert (e["client"], e["project"], e["project_code"], e["task_name"]) == ("Test Client A", "Statutory Audit FY26", "PL-T001", "Planning and scoping")
    assert (e["hours"], e["remarks"], e["task_status"]) == (None, "Kick-off", "in_progress") and b["location"] == "Client Site"
    doc = api.db["t_entries"].find_one({"employee_id": "JHS9101"})
    assert doc["reporting_manager"] == "JHS9001" and doc["reporting_manager_name"] == "Manager A" and doc["activity"] == "Kick-off"
    assert doc["location"] == "Client Site" and doc["cycle_id"] == "2026-10-C2" and doc["approved"] is False
    assert api.db["t_drafts"].find_one({"employee_id": "JHS9101", "date": DAY})["location"] == "Client Site"
    assert b["submitted"] is False


def test_saving_again_replaces_rows_and_keeps_created_at(api):
    put(api, [row(1, 4), row(2, 3)])
    first = api.db["t_entries"].find_one({"task_id": 1})["created_at"]
    r = put(api, [row(1, 5)], location="Work From Home")
    assert [e["task_id"] for e in r.json()["entries"]] == [1] and r.json()["totals"]["task_hours"] == 5
    assert api.db["t_entries"].count_documents({"employee_id": "JHS9101"}) == 1
    assert api.db["t_entries"].find_one({"task_id": 1})["created_at"] == first and api.db["t_entries"].find_one()["location"] == "Work From Home"


@pytest.mark.parametrize("entries,location,code", [
    ([row(1, 4), row(1, 2)], "Office", 422),                                         # same task twice
    ([row(13, 4)], "Office", 422),                                                   # assigned to someone else
    ([row(4, 4)], "Office", 422),                                                    # finished and not overdue: not offered
    ([row(1, -1)], "Office", 422), ([row(1, 25)], "Office", 422), ([row(1, 8.333)], "Office", 422),
    ([row(1, 4, status="paused")], "Office", 422),                                   # unknown status
    ([row(1, 4, unplanned=True)], "Office", 422),                                    # unplanned row cannot carry a task
    ([row(1, 4)], "Moon", 422),                                                      # unknown location
    ([row(1, 4)], "Leave", 422), ([row(1, 4)], "Week Off", 422), ([row(1, 4)], "PHY", 422),   # a day off carries no rows
])
def test_draft_validation(api, entries, location, code):
    assert put(api, entries, location).status_code == code
    assert api.db["t_entries"].count_documents({}) == 0


def test_too_many_rows(api):
    assert put(api, [unplanned(1, "x" * 5)] * 21).status_code == 422


def test_unplanned_row_keeps_its_description_as_the_reason(api):
    r = put(api, [row(1, 3), unplanned(1, "Ad-hoc data pull asked by partner")])
    assert r.status_code == 200
    u = api.db["t_entries"].find_one({"is_unplanned": True})
    assert (u["unplanned_reason"], u["remarks"], u["client"], u["project_code"], u["task_id"]) == \
           ("Ad-hoc data pull asked by partner", "Ad-hoc data pull asked by partner", "", "", None)


def test_a_failed_save_never_empties_the_day(api, monkeypatch):
    put(api, [row(1, 4), row(2, 3)])
    monkeypatch.setattr(daily.store.entries, "insert_many", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db down")))
    with pytest.raises(RuntimeError):
        put(api, [row(1, 2)])
    assert api.db["t_entries"].count_documents({"employee_id": "JHS9101"}) == 2


# ── submitting ───────────────────────────────────────────────────────────────

def test_submit_is_strict(api):
    assert put(api, []).status_code == 200 and "Add at least one task" in submit(api).json()["detail"]
    put(api, [row(1, None, remarks="x")])
    assert "Row 1: enter hours" in submit(api).json()["detail"]
    put(api, [row(1, 12), row(2, 13)])
    assert "add up to 25" in submit(api).json()["detail"]
    put(api, [row(1, 4), unplanned(2, "  ")])
    assert "Row 2: describe the unplanned work" in submit(api).json()["detail"]
    assert api.db["t_submissions"].count_documents({}) == 0


def test_submit_marks_the_day_and_clears_the_draft(api):
    put(api, [row(1, 4.5, "done", "Tested POs"), row(2, 3.5)], location="Client Site")
    r = submit(api)
    assert r.status_code == 200 and r.json()["submitted"] is True and r.json()["totals"]["task_hours"] == 8.0
    sub = api.db["t_submissions"].find_one({"employee_id": "JHS9101", "date": DAY})
    assert sub["location"] == "Client Site" and sub["cycle_id"] == "2026-10-C2" and sub["submitted_at"]
    assert api.db["t_drafts"].count_documents({}) == 0 and r.json()["location"] == "Client Site"


def test_a_submitted_day_is_locked_until_an_admin_allows_changes(api):
    put(api, [row(1, 8)])
    assert submit(api).status_code == 200 and states(strip(api))[DAY] == "submitted"
    r = put(api, [row(1, 7.5)])
    assert r.status_code == 409 and "submitted" in r.json()["detail"]                       # no editing ...
    assert submit(api).status_code == 409                                                  # ... and no second submit
    b = get_day(api).json()
    assert b["read_only"] is True and b["read_only_reason"] == "submitted" and b["submitted"] is True
    api.db["t_submissions"].update_one({"date": DAY}, {"$set": {"reopened": {"by": "JHS9000", "reason": "wrong hours"}}})
    assert get_day(api).json()["read_only"] is False and get_day(api).json()["day_reopened"] is True
    assert put(api, [row(1, 7.5)]).json()["submitted"] is False                            # allowed once; the submission is withdrawn
    assert submit(api).status_code == 200
    assert "reopened" not in api.db["t_submissions"].find_one({"date": DAY})
    assert put(api, [row(1, 6)]).status_code == 409                                         # locked again after the new submit


def test_sending_a_cycle_back_opens_its_submitted_days(api):
    put(api, [row(1, 8)])
    submit(api)
    api.db["t_reviews"].insert_one({"kind": "approval", "employee_id": "JHS9101", "cycle_id": "2026-10-C2",
                                    "status": "sent_back", "note": "check"})
    assert put(api, [row(1, 7)]).status_code == 200


def test_days_outside_an_admin_created_payroll_are_closed(api):
    b = get_day(api, day="2026-09-10").json()                                              # no payroll for early September yet
    assert b["read_only_reason"] == "no_cycle" and b["cycle"]["configured"] is False
    assert put(api, [row(1, 4)], day="2026-09-10").status_code == 409
    assert get_day(api).json()["cycle"]["configured"] is True


def test_the_admins_deadline_is_used(api):
    api.db["t_payrolls"].update_one({"_id": "2026-10"}, {"$set": {"cycles.$[c].deadline": "2026-10-22"}}, array_filters=[{"c.id": "2026-10-C2"}])
    payrolls.invalidate()
    b = get_day(api).json()
    assert b["cycle"]["deadline"] == "2026-10-22"
    assert put(api, [row(1, 4)], day=DAY).status_code == 200                                # still open on the 16th


def test_day_off_needs_no_rows(api):
    for loc in ("Leave", "Week Off", "PHY"):
        day = {"Leave": "2026-10-13", "Week Off": "2026-10-12", "PHY": "2026-10-15"}[loc]
        assert put(api, [], loc, day=day).status_code == 200
        assert submit(api, day=day).status_code == 200
        s = api.db["t_submissions"].find_one({"date": day})
        assert s["location"] == loc
    assert states(strip(api))["2026-10-13"] == "submitted"
    assert [d["location"] for d in strip(api).json()["days"] if d["date"] == "2026-10-13"] == ["Leave"]


def test_submit_needs_a_saved_location(api):
    assert submit(api).status_code == 422 and "location" in submit(api).json()["detail"]


# ── the day strip ────────────────────────────────────────────────────────────

def test_day_strip_states_and_summary(api):
    b = strip(api).json()
    assert b["cycle"]["id"] == "2026-10-C2" and b["today"] == "2026-10-16" and len(b["days"]) == 10
    st = states(strip(api))
    assert st["2026-10-11"] == "off"                                                  # Sunday, nothing there
    assert [st[f"2026-10-{d}"] for d in (12, 13, 14, 15)] == ["missing"] * 4
    assert st["2026-10-16"] == "open" and st["2026-10-17"] == "future"
    assert b["summary"] == {"submitted": 0, "saved": 0, "missing": 5}                  # four missing days + today still to do
    put(api, [row(1, 4)])
    put(api, [], "Leave", day="2026-10-13"); submit(api, day="2026-10-13")
    st = states(strip(api))
    assert st[DAY] == "saved" and st["2026-10-13"] == "submitted"
    assert strip(api).json()["summary"] == {"submitted": 1, "saved": 1, "missing": 3}
    assert b["prev_date"] == "2026-10-10" and b["next_date"] is None                  # this cycle has not ended
    old = strip(api, date="2026-10-05").json()
    assert old["cycle"]["id"] == "2026-10-C1" and old["next_date"] == "2026-10-11"


def test_holiday_and_weekend_are_not_missing(api):
    st = states(strip(api, date="2026-10-01"))
    assert st["2026-10-02"] == "off" and st["2026-10-03"] == "off" and st["2026-10-04"] == "off"      # holiday + weekend
    assert st["2026-10-01"] == "missing" and st["2026-10-05"] == "missing"


# ── read-only days ───────────────────────────────────────────────────────────

def test_approved_or_locked_days_are_read_only(api):
    put(api, [row(1, 4)])
    api.db["t_entries"].update_many({"employee_id": "JHS9101"}, {"$set": {"approved": True}})
    assert put(api, [row(1, 1)]).status_code == 409 and submit(api).status_code == 409
    assert api.db["t_entries"].count_documents({"employee_id": "JHS9101"}) == 1
    b = get_day(api).json()
    assert b["read_only"] is True and b["read_only_reason"] == "approved"


def test_an_approved_cycle_blocks_even_empty_days(api):
    api.db["t_reviews"].insert_one({"kind": "approval", "employee_id": "JHS9101", "cycle_id": "2026-10-C2", "status": "approved"})
    r = put(api, [row(1, 4)], day="2026-10-15")
    assert r.status_code == 409 and "approved" in r.json()["detail"]
    api.db["t_reviews"].update_one({"employee_id": "JHS9101"}, {"$set": {"status": "reopened"}})
    assert put(api, [row(1, 4)], day="2026-10-15").status_code == 200


def test_the_deadline_closes_the_sub_cycle(api, monkeypatch):
    put(api, [row(1, 4)])
    monkeypatch.setattr(daily, "_now_ist", lambda: datetime(2026, 10, 25, 23, 59, 0))
    assert put(api, [row(1, 5)]).status_code == 200                                   # still open at 23:59
    monkeypatch.setattr(daily, "_now_ist", lambda: datetime(2026, 10, 26, 0, 0, 1))
    r = put(api, [row(1, 6)])
    assert r.status_code == 409 and "deadline" in r.json()["detail"]
    assert submit(api).status_code == 409
    b = get_day(api).json()
    assert b["read_only"] is True and b["read_only_reason"] == "deadline" and b["cycle"]["deadline_passed"] is True


def test_everyone_is_enabled_by_default_except_free_text_employees(api):
    api.db["t_config"].update_one({"_id": "timesheet"}, {"$unset": {"timesheet_scope": ""}, "$set": {"pilot_employees": []}})
    api.db["t_employees"].insert_one({"EmpID": "JHS7777", "PartnerEmpCode": "JHS02", "ReportingEmpCode": "JHS9001"})
    _user["id"] = "JHS7777"
    assert api.get("/timesheet/v2/enabled/JHS7777").json()["enabled"] is True          # not on any list
    _user["id"] = "JHS1562"
    assert api.get("/timesheet/v2/enabled/JHS1562").json()["enabled"] is False         # free-text employee: classic
    api.db["t_config"].update_one({"_id": "timesheet"}, {"$set": {"timesheet_scope": "pilot"}})
    _user["id"] = "JHS7777"
    assert api.get("/timesheet/v2/enabled/JHS7777").json()["enabled"] is False         # staged roll-out switched on


def test_a_named_free_text_employee_can_be_included(api):
    api.db["t_employees"].insert_one({"EmpID": "JHS1191", "PartnerEmpCode": "JHS01", "ReportingEmpCode": "JHS9001"})
    api.db["t_config"].update_one({"_id": "timesheet"}, {"$unset": {"timesheet_scope": ""}})
    _user["id"] = "JHS1191"
    assert api.get("/timesheet/v2/enabled/JHS1191").json()["enabled"] is False         # JHS01 rule still applies
    api.db["t_config"].update_one({"_id": "timesheet"}, {"$set": {"new_timesheet_include": ["jhs1191"]}})
    assert api.get("/timesheet/v2/enabled/JHS1191").json()["enabled"] is True
    assert api.get(f"/timesheet/v2/day/JHS1191?date={DAY}").status_code == 200
    _user["id"] = "JHS1562"
    assert api.get("/timesheet/v2/enabled/JHS1562").json()["enabled"] is False         # others are unaffected
    from backend.timesheet import scope
    cfg = api.db["t_config"].find_one({"_id": "timesheet"})
    assert "JHS1191" in scope.enabled_set(api.db["t_config"], api.db["t_employees"])
    assert scope.is_enabled("JHS1562", cfg, api.db["t_employees"]) is False


def test_a_sent_back_cycle_is_editable_after_the_deadline_with_the_note_shown(api, monkeypatch):
    put(api, [row(1, 4)])
    monkeypatch.setattr(daily, "_now_ist", lambda: datetime(2026, 10, 26, 0, 0, 1))
    assert put(api, [row(1, 6)]).status_code == 409
    api.db["t_reviews"].insert_one({"kind": "approval", "employee_id": "JHS9101", "cycle_id": "2026-10-C2",
                                    "status": "sent_back", "note": "Fix the hours on the 14th"})
    assert put(api, [row(1, 6)]).status_code == 200 and submit(api).status_code == 200
    b = get_day(api).json()
    assert b["read_only"] is False and b["cycle"]["review_status"] == "sent_back"
    assert b["cycle"]["review_note"] == "Fix the hours on the 14th"
    api.db["t_reviews"].update_one({"employee_id": "JHS9101"}, {"$set": {"status": "approved"}})
    b = get_day(api).json()
    assert b["read_only_reason"] == "approved" and b["cycle"]["review_note"] is None


def test_days_from_the_classic_timesheet_are_view_only(api):
    api.db["t_entries"].insert_one({"employee_id": "JHS9101", "date": DAY, "legacy": True, "task_id": None,
                                    "task_name": "Old activity text", "hours": 8, "location": "Office",
                                    "client": "C", "project": "P", "project_code": "PL1", "created_at": NOW})
    b = get_day(api).json()
    assert b["read_only_reason"] == "classic" and b["entries"][0]["legacy"] is True and "classic" in b["read_only_text"]
    assert put(api, [row(1, 4)]).status_code == 409
    assert strip(api).json()["days"][3]["classic"] is True


# ── NQ outage ────────────────────────────────────────────────────────────────

def test_nq_down_page_still_loads_and_only_nq_dependent_saves_fail(api):
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    repository.configure(dev_settings(port=port, connect_timeout=1))
    b = get_day(api).json()
    assert b["tasks"] == [] and b["nq_unavailable"] and b["nq_data_may_be_stale"]
    assert put(api, [row(1, 4)]).status_code == 503
    assert put(api, [unplanned(2, "Client call not in NQ")]).status_code == 200      # unplanned work needs no NQ
    assert put(api, [], "Leave", day="2026-10-13").status_code == 200


def test_me_endpoint_reports_roles_for_the_menu(api, monkeypatch):
    from backend.metrics import access
    from backend.timesheet import me
    monkeypatch.setattr(me.store, "employees", api.db["t_employees"])
    monkeypatch.setattr(me, "config_doc", lambda: api.db["t_config"].find_one({"_id": "timesheet"}) or {})
    monkeypatch.setattr(access, "is_admin", lambda u: u == "JHS9001")
    monkeypatch.setattr(access, "is_partner", lambda u: False)
    monkeypatch.setattr(access, "is_manager", lambda u: u == "JHS9001")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    app = FastAPI()
    app.include_router(me.router)
    app.dependency_overrides[get_current_user] = lambda: _user["id"]
    c = TestClient(app)
    api.db["t_employees"].insert_one({"EmpID": "JHS9001", "Emp Name": "Manager A", "PartnerEmpCode": "JHS02"})
    _user["id"] = "JHS9101"
    b = c.get("/timesheet/v2/me").json()
    assert b["employee_id"] == "JHS9101" and b["new_timesheet"] is True
    assert (b["is_admin"], b["is_manager"], b["has_reportees"]) == (False, False, False)
    _user["id"] = "JHS9001"
    b = c.get("/timesheet/v2/me").json()
    assert b["name"] == "Manager A" and b["is_admin"] is True and b["has_reportees"] is True and b["is_manager"] is True


def test_page_endpoint_gives_enabled_day_and_strip_in_one_request(api):
    b = api.get(f"/timesheet/v2/page/JHS9101?date={DAY}").json()
    assert b["enabled"] is True and b["day"]["date"] == DAY and b["strip"]["selected"] == DAY
    assert b["day"] == api.get(f"/timesheet/v2/day/JHS9101?date={DAY}").json()
    assert b["strip"] == api.get(f"/timesheet/v2/cycle-days/JHS9101?date={DAY}").json()
    assert api.get("/timesheet/v2/page/JHS9101").json()["day"]["date"] == "2026-10-16"            # default: today
    _user["id"] = "JHS1562"
    assert api.get("/timesheet/v2/page/JHS1562").json() == {"enabled": False, "reason": "free_text_employee"}
    _user["id"] = "JHS9101"
    assert api.get("/timesheet/v2/page/JHS9102").status_code == 403                               # only your own page


def test_the_optional_remarks_box_is_stored_returned_and_copied(api):
    b = put(api, [row(1, 4, remarks="reviewed the file", extra_remarks="client asked for another sample")]).json()
    assert b["entries"][0]["remarks"] == "reviewed the file" and b["entries"][0]["extra_remarks"] == "client asked for another sample"
    assert api.db["t_entries"].find_one({"employee_id": "JHS9101"})["extra_remarks"] == "client asked for another sample"
    assert get_day(api).json()["entries"][0]["extra_remarks"] == "client asked for another sample"
    assert put(api, [row(1, 4)]).json()["entries"][0]["extra_remarks"] == ""                 # optional: empty is fine
    assert put(api, [unplanned(2, "did an unplanned thing")]).status_code == 200            # unplanned still needs only its reason
    assert put(api, [row(1, 4, extra_remarks="x" * 1001)]).status_code == 422               # same 1000-character limit
