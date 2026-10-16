"""
API tests for the hours-only daily timesheet. Need the Docker dev stack
(docker compose -f docker-compose.dev.yml up -d): MySQL on 3308 (seeded fake NQ) and
Mongo on 27018 (scratch database 'timesnap_test'). Never touches .env or real data.
Seed reference: tests use 2026-10-14; JHS9101 has NQ tasks 1,2,3,5 that day.
"""
import os
import socket

import pytest

os.environ.setdefault("MONGO_CONNECTION_STRING", "mongodb://localhost:27018/")

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pymongo import MongoClient

from backend.auth import get_current_user
from backend.nq import cache, repository
from backend.timesheet import daily
from tests.nq.conftest import DEV_PORT, dev_settings

MONGO_PORT = int(os.getenv("MONGO_DEV_PORT", "27018"))
DAY = "2026-10-14"


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
    for name in ("entries", "submissions", "hrms", "config", "employees"):
        db[f"t_{name}"].drop()
    monkeypatch.setattr(daily.store, "entries", db["t_entries"])
    monkeypatch.setattr(daily.store, "submissions", db["t_submissions"])
    monkeypatch.setattr(daily.store, "hrms", db["t_hrms"])
    monkeypatch.setattr(daily.store, "config", db["t_config"])
    monkeypatch.setattr(daily.store, "employees", db["t_employees"])
    db["t_config"].insert_one({"_id": "timesheet",
                               "pilot_employees": ["JHS9101", "JHS9102", "JHS1562"],
                               "holidays": ["2026-10-02"]})
    db["t_employees"].insert_many([
        {"EmpID": "JHS9101", "PartnerEmpCode": "JHS02"},
        {"EmpID": "JHS9102", "PartnerEmpCode": "JHS02"},
        {"EmpID": "JHS1562", "PartnerEmpCode": "JHS02"},   # free-text employee, always excluded
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


def put(c, emp, day, entries):
    return c.put(f"/timesheet/v2/day/{emp}/{day}", json={"entries": entries})


def e(task_id, hours=None, status="in_progress", activity="did work", **kw):
    return {"task_id": task_id, "hours": hours, "task_status": status, "activity": activity, **kw}


def add_hrms(c, emp, day, net, leave=False):
    c.db["t_hrms"].insert_one({"employee_id": emp, "date": day, "in_time": "09:30",
                               "out_time": "18:30", "gross_hours": net + 0.5,
                               "net_hours": net, "leave_flag": leave})


# ── role checks ──────────────────────────────────────────────────────────────

def test_cannot_touch_another_employees_day(api):
    assert api.get(f"/timesheet/v2/day/JHS9102?date={DAY}").status_code == 403
    assert put(api, "JHS9102", DAY, [e(5, 1)]).status_code == 403
    assert api.post(f"/timesheet/v2/day/JHS9102/{DAY}/submit", json={}).status_code == 403
    assert api.get("/timesheet/v2/enabled/JHS9102").status_code == 403


def test_not_in_pilot_is_forbidden(api):
    _user["id"] = "JHS9103"
    assert api.get("/timesheet/v2/enabled/JHS9103").json() == {"enabled": False}
    assert api.get(f"/timesheet/v2/day/JHS9103?date={DAY}").status_code == 403
    assert put(api, "JHS9103", DAY, [e(6, 1)]).status_code == 403


def test_free_text_employee_excluded_even_if_listed(api):
    _user["id"] = "JHS1562"
    assert api.get("/timesheet/v2/enabled/JHS1562").json() == {"enabled": False}
    assert api.get(f"/timesheet/v2/day/JHS1562?date={DAY}").status_code == 403


# ── reading a day ────────────────────────────────────────────────────────────

def test_my_tasks_panel_has_budget_and_usage(api):
    body = api.get(f"/timesheet/v2/day/JHS9101?date={DAY}").json()
    assert sorted(t["task_id"] for t in body["tasks"]) == [1, 2, 3, 5]
    t1 = next(t for t in body["tasks"] if t["task_id"] == 1)   # 2026-10-01..31, holiday 10-02
    assert t1["budget_hours"] == 21 * 8.5 and t1["project_code"] == "PL-T001"
    assert next(t for t in body["tasks"] if t["task_id"] == 3)["is_overdue"] is True
    assert body["cycle"]["id"] == "2026-10-C2" and body["hrms"] is None
    assert body["allocation_assumed_100"] is True


def test_future_date_and_bad_date_rejected(api):
    assert api.get("/timesheet/v2/day/JHS9101?date=2999-01-01").status_code == 400
    assert api.get("/timesheet/v2/day/JHS9101?date=not-a-date").status_code == 400


# ── saving ───────────────────────────────────────────────────────────────────

def test_one_task_day_awaiting_hrms_then_nq_fields_copied(api):
    r = put(api, "JHS9101", DAY, [e(1, 5, client="EVIL", project="EVIL", project_code="EVIL")])
    assert r.status_code == 200
    row = r.json()["entries"][0]
    assert row["hours"] is None and row["awaiting_hrms"] is True      # browser hours ignored
    assert (row["client"], row["project_code"]) == ("Test Client A", "PL-T001")
    assert r.json()["totals"]["awaiting_hrms"] is True


def test_one_task_day_locked_to_hrms_net(api):
    add_hrms(api, "JHS9101", DAY, 8.0)
    row = put(api, "JHS9101", DAY, [e(1, 3)]).json()["entries"][0]
    assert row["hours"] == 8.0 and row["awaiting_hrms"] is False


def test_multi_task_day_uses_entered_hours_and_validates(api):
    add_hrms(api, "JHS9101", DAY, 8.5)
    body = put(api, "JHS9101", DAY, [e(1, 4), e(2, 4.25)]).json()
    assert body["totals"]["task_hours"] == 8.25 and body["totals"]["within_tolerance"] is True
    assert put(api, "JHS9101", DAY, [e(1, 4), e(2, 0.3)]).status_code == 422     # step
    assert put(api, "JHS9101", DAY, [e(1, 4), e(2, None)]).status_code == 422    # missing
    assert put(api, "JHS9101", DAY, [e(1, 4), e(1, 4)]).status_code == 422       # duplicate task


def test_task_not_assigned_is_rejected(api):
    assert put(api, "JHS9101", DAY, [e(13, 4), e(1, 4)]).status_code == 422      # task 13 -> user 13
    assert put(api, "JHS9101", DAY, [e(4, 4), e(1, 4)]).status_code == 422       # done overdue, not listed


def test_unplanned_needs_reason_and_copies_project(api):
    bad = {"task_id": None, "is_unplanned": True, "hours": 2, "task_status": "done", "activity": "x"}
    assert put(api, "JHS9101", DAY, [bad, e(1, 4)]).status_code == 422
    ok = dict(bad, unplanned_reason="client call", project_code="PL-T002")
    rows = put(api, "JHS9101", DAY, [ok, e(1, 4)]).json()["entries"]
    un = next(r for r in rows if r["is_unplanned"])
    assert (un["client"], un["project_code"], un["unplanned_reason"]) == ("Test Client A", "PL-T002", "client call")
    assert put(api, "JHS9101", DAY, [dict(ok, project_code="NOPE"), e(1, 4)]).status_code == 422


def test_hours_used_reflects_saved_entries(api):
    put(api, "JHS9101", DAY, [e(1, 4), e(2, 3)])
    body = api.get(f"/timesheet/v2/day/JHS9101?date={DAY}").json()
    assert next(t for t in body["tasks"] if t["task_id"] == 1)["hours_used"] == 4.0


# ── submit / reconciliation reason / locks ───────────────────────────────────

def test_submit_requires_reason_outside_tolerance(api):
    add_hrms(api, "JHS9101", DAY, 8.5)
    put(api, "JHS9101", DAY, [e(1, 3), e(2, 3)])          # 6.0 vs 8.5 -> short
    assert api.post(f"/timesheet/v2/day/JHS9101/{DAY}/submit", json={}).status_code == 422
    r = api.post(f"/timesheet/v2/day/JHS9101/{DAY}/submit", json={"reco_reason": "client meeting"})
    assert r.status_code == 200 and r.json()["submitted"] and r.json()["reco_reason"] == "client meeting"


def test_submit_within_tolerance_needs_no_reason_and_clears_it(api):
    add_hrms(api, "JHS9101", DAY, 8.5)
    put(api, "JHS9101", DAY, [e(1, 4), e(2, 4.25)])
    r = api.post(f"/timesheet/v2/day/JHS9101/{DAY}/submit", json={"reco_reason": "ignored"})
    assert r.status_code == 200 and r.json()["reco_reason"] == ""


def test_submit_without_entries_fails_and_without_hrms_ok(api):
    assert api.post(f"/timesheet/v2/day/JHS9101/{DAY}/submit", json={}).status_code == 422
    put(api, "JHS9101", DAY, [e(1, 4), e(2, 3)])           # no HRMS yet -> nothing to reconcile
    assert api.post(f"/timesheet/v2/day/JHS9101/{DAY}/submit", json={}).status_code == 200


def test_editing_submitted_day_withdraws_submission(api):
    put(api, "JHS9101", DAY, [e(1, 4), e(2, 3)])
    api.post(f"/timesheet/v2/day/JHS9101/{DAY}/submit", json={})
    assert put(api, "JHS9101", DAY, [e(1, 5), e(2, 3)]).json()["submitted"] is False


def test_locked_day_is_read_only(api):
    put(api, "JHS9101", DAY, [e(1, 4), e(2, 3)])
    api.db["t_entries"].update_many({"employee_id": "JHS9101"}, {"$set": {"locked": True}})
    assert put(api, "JHS9101", DAY, [e(1, 1), e(2, 1)]).status_code == 409
    assert api.post(f"/timesheet/v2/day/JHS9101/{DAY}/submit", json={}).status_code == 409
    assert api.get(f"/timesheet/v2/day/JHS9101?date={DAY}").json()["locked"] is True


# ── NQ outage ────────────────────────────────────────────────────────────────

def test_nq_down_page_still_loads_and_planned_save_is_503(api):
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    repository.configure(dev_settings(port=port, connect_timeout=1))   # also clears the cache
    body = api.get(f"/timesheet/v2/day/JHS9101?date={DAY}").json()
    assert body["tasks"] == [] and body["nq_unavailable"] and body["nq_data_may_be_stale"]
    assert put(api, "JHS9101", DAY, [e(1, 4), e(2, 3)]).status_code == 503
