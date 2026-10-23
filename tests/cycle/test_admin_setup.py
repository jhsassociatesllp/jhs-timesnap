"""Admin setup API: payrolls, working rules, who uses My day, allowing changes to a submitted day. Scratch Mongo only."""
from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.auth import get_current_user
from backend.metrics import access
from backend.timesheet import admin as adm, payrolls
from tests.cycle.conftest import entry

_user = {"id": "JHS9000"}


@pytest.fixture
def api(cdb, monkeypatch):
    monkeypatch.setattr(access, "has_admin_module", lambda emp, key: emp == "JHS9000" and key == "timesheet")
    cdb["c_payrolls"].drop()
    payrolls.invalidate()
    app = FastAPI()
    app.include_router(adm.router)
    app.dependency_overrides[get_current_user] = lambda: _user["id"]
    _user["id"] = "JHS9000"
    c = TestClient(app)
    c.db = cdb
    return c


B = "/timesheet/v2/admin"


def test_only_admins_can_use_every_endpoint(api):
    calls = [("get", f"{B}/overview", None), ("post", f"{B}/payrolls", {"month": "2026-10"}),
             ("put", f"{B}/payrolls/2026-10/cycles/2026-10-C2", {"deadline": "2026-10-30"}), ("delete", f"{B}/payrolls/2026-10", None),
             ("put", f"{B}/settings", {"standard_hours": 8, "week_off_days": [6], "deadline_days": 5}),
             ("put", f"{B}/access", {"scope": "all"}), ("get", f"{B}/submitted-days?employee=JHS9101&from=2026-10-01&to=2026-10-31", None),
             ("post", f"{B}/reopen-day", {"employee_id": "JHS9101", "date": "2026-10-12", "reason": "fix"})]
    for who in ("JHS9101", "JHS9001"):                                         # an employee, a manager
        _user["id"] = who
        for method, url, body in calls:
            r = getattr(api, method)(url, **({"json": body} if body is not None else {}))
            assert r.status_code == 403, (who, method, url)


def test_create_payroll_gives_three_cycles_and_rejects_duplicates(api):
    r = api.post(f"{B}/payrolls", json={"month": "2026-10"})
    assert r.status_code == 200 and r.json()["label"] == "21 Sep - 20 Oct 2026"
    assert [(c["id"], c["deadline"]) for c in r.json()["cycles"]] == [
        ("2026-09-C3", "2026-10-05"), ("2026-10-C1", "2026-10-15"), ("2026-10-C2", "2026-10-25")]
    assert payrolls.is_configured("2026-10-C2") and not payrolls.is_configured("2026-10-C3")
    assert api.post(f"{B}/payrolls", json={"month": "2026-10"}).status_code == 409
    assert api.post(f"{B}/payrolls", json={"month": "2026-13"}).status_code == 422
    assert api.post(f"{B}/payrolls", json={"month": "2026-11", "deadline_days": 3}).json()["cycles"][0]["deadline"] == "2026-11-03"
    ov = api.get(f"{B}/overview").json()
    assert [p["_id"] for p in ov["payrolls"]] == ["2026-11", "2026-10"]
    assert api.db["c_reviews"].count_documents({"kind": "admin_change", "what": "payroll created"}) == 2        # audited


def test_deadline_edit_and_delete_rules(api):
    api.post(f"{B}/payrolls", json={"month": "2026-10"})
    url = f"{B}/payrolls/2026-10/cycles/2026-10-C2"
    assert api.put(url, json={"deadline": "2026-10-19"}).status_code == 422                 # before the cycle ends
    assert api.put(url, json={"deadline": "nope"}).status_code == 422
    assert api.put(url, json={"deadline": "2026-11-02"}).status_code == 200
    assert payrolls.cycle_config("2026-10-C2")["deadline"] == "2026-11-02"
    assert api.put(f"{B}/payrolls/2026-10/cycles/2026-10-C3", json={"deadline": "2026-11-02"}).status_code == 404
    api.db["c_entries"].insert_one(entry("JHS9101", "2026-10-12", 8))
    assert api.delete(f"{B}/payrolls/2026-10").status_code == 409                          # it has data
    api.post(f"{B}/payrolls", json={"month": "2026-12"})
    assert api.delete(f"{B}/payrolls/2026-12").status_code == 200 and not payrolls.is_configured("2026-12-C1")
    assert api.delete(f"{B}/payrolls/2026-12").status_code == 404


def test_working_rules_are_validated_and_applied(api):
    ok = {"standard_hours": 8, "week_off_days": [6], "deadline_days": 7,
          "holidays": [{"date": "2026-10-02", "name": "Gandhi Jayanti"}, {"date": "2026-10-20", "name": ""}]}
    assert api.put(f"{B}/settings", json=ok).status_code == 200
    st = payrolls.settings_from(api.db["c_config"].find_one({"_id": "timesheet"}))
    assert st["standard_hours"] == 8.0 and st["week_off"] == (6,) and st["deadline_days"] == 7
    assert sorted(d.isoformat() for d in st["holidays"]) == ["2026-10-02", "2026-10-20"]
    shown = api.get(f"{B}/overview").json()["settings"]
    assert shown["week_off_days"] == [6] and shown["holidays"][0] == {"date": "2026-10-02", "name": "Gandhi Jayanti"}
    for bad in ({**ok, "standard_hours": 0}, {**ok, "standard_hours": 25}, {**ok, "week_off_days": [0, 1, 2, 3, 4, 5, 6]},
                {**ok, "week_off_days": [7]}, {**ok, "deadline_days": -1}, {**ok, "holidays": [{"date": "x"}]}):
        assert api.put(f"{B}/settings", json=bad).status_code in (422, 400)
    assert api.post(f"{B}/payrolls", json={"month": "2026-10"}).json()["cycles"][0]["deadline"] == "2026-10-07"     # new default


def test_access_scope_and_codes(api):
    assert api.put(f"{B}/access", json={"scope": "pilot", "pilot_employees": ["jhs9101", "JHS9102"], "include": ["JHS1191"]}).status_code == 200
    doc = api.db["c_config"].find_one({"_id": "timesheet"})
    assert doc["timesheet_scope"] == "pilot" and doc["pilot_employees"] == ["JHS9101", "JHS9102"] and doc["new_timesheet_include"] == ["JHS1191"]
    assert api.put(f"{B}/access", json={"scope": "pilot", "pilot_employees": ["bad code;"]}).status_code == 422
    assert api.put(f"{B}/access", json={"scope": "everyone"}).status_code == 422
    assert api.get(f"{B}/overview").json()["access"]["scope"] == "pilot"


def test_allow_changes_to_a_submitted_day(api):
    now = datetime.utcnow()
    api.db["c_submissions"].insert_many([
        {"employee_id": "JHS9101", "date": "2026-10-12", "location": "Office", "cycle_id": "2026-10-C2", "submitted_at": now},
        {"employee_id": "JHS9101", "date": "2026-10-13", "location": "Office", "cycle_id": "2026-10-C2", "submitted_at": now, "legacy": True}])
    api.db["c_entries"].insert_one(entry("JHS9101", "2026-10-12", 8))
    days = api.get(f"{B}/submitted-days?employee=jhs9101&from=2026-10-01&to=2026-10-31").json()["days"]
    assert [(d["date"], d["hours"], d["reopened"]) for d in days] == [("2026-10-12", 8.0, None), ("2026-10-13", 0.0, None)]
    body = {"employee_id": "JHS9101", "date": "2026-10-12", "reason": "Wrong project picked"}
    assert api.post(f"{B}/reopen-day", json={**body, "reason": "x"}).status_code == 422
    assert api.post(f"{B}/reopen-day", json={**body, "date": "2026-10-14"}).status_code == 404            # not submitted
    assert api.post(f"{B}/reopen-day", json={**body, "date": "2026-10-13"}).status_code == 409           # a classic day
    assert api.post(f"{B}/reopen-day", json=body).status_code == 200
    assert api.db["c_submissions"].find_one({"date": "2026-10-12"})["reopened"]["by"] == "JHS9000"
    assert api.db["c_reviews"].find_one({"kind": "day_reopen"})["reason"] == "Wrong project picked"
    assert api.post(f"{B}/reopen-day", json=body).status_code == 409                                      # already open
    api.db["c_submissions"].update_one({"date": "2026-10-12"}, {"$unset": {"reopened": ""}})
    api.db["c_reviews"].insert_one({"kind": "approval", "employee_id": "JHS9101", "cycle_id": "2026-10-C2", "status": "approved"})
    assert api.post(f"{B}/reopen-day", json=body).status_code == 409                                      # the manager approved it
    assert api.get(f"{B}/submitted-days?employee=JHS9101&from=2026-01-01&to=2026-12-31").status_code == 422   # range too long
