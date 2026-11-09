"""Dashboard API: role scoping and content. Data is written straight into the (scratch) aggregate
collections, so these tests also prove the dashboards need neither NQ nor raw timesheet entries."""
from datetime import date, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.auth import get_current_user
from backend.metrics import access
from backend.metrics import router as dr
from backend.nq import repository

ADMINS = {"JHS9000"}
_user = {"id": "JHS9001"}


def proj(code, mgrs, rag, **kw):
    base = {"date": "2026-10-15", "project_code": code, "project_name": f"Project {code}", "client_name": "Client",
            "manager_emp_ids": mgrs, "partner_emp_id": "JHS9050", "rag": rag, "budget_hours": 100, "hours_used": 40,
            "hours_new": 30, "hours_legacy": 10, "hours_used_pct": 40, "tasks_total": 10, "tasks_done": 4,
            "tasks_done_pct": 40, "overdue_tasks": 0, "days_since_last_entry": 1, "planned_end": "2026-10-31",
            "forecast_end": "2026-10-31", "gap_points": 0.0, "computed_at": datetime.utcnow()}
    base.update(kw)
    return base


def daily(day, mgr, expected, submitted, entries, unplanned, reco, size=2, hours=16.0):
    full = {k: 0 for k in ("matched", "short", "over", "no_punch", "not_filled", "leave")}
    full.update(reco)
    return {"date": day, "manager_id": mgr, "team_size": size, "expected": expected, "submitted": submitted,
            "hours": hours, "entries": entries, "unplanned": unplanned, "reco": full}


def team(emp, mgr, load, streak, day="2026-10-15"):
    return {"date": day, "employee_id": emp, "manager_id": mgr, "load_pct": load, "remaining_hours": load * 0.85,
            "capacity_hours": 85.0, "open_tasks": 3, "window_end": "2026-10-28", "missing_streak": streak, "is_pilot": True}


@pytest.fixture
def api(mdb, monkeypatch):
    monkeypatch.setattr(access, "has_admin_module", lambda emp, key: emp in ADMINS and key == "timesheet")
    monkeypatch.setattr(dr, "_today", lambda: date(2026, 10, 16))
    mdb["c_employees"].insert_many([
        {"EmpID": "JHS9050", "Emp Name": "Partner P", "Grade Name": "PND", "ReportingEmpCode": ""},
        {"EmpID": "JHS9200", "Emp Name": "Plain Employee", "Grade Name": "E", "ReportingEmpCode": "JHS9300"}])
    mdb["m_projects"].insert_many([
        proj("PL-A", ["JHS9001"], "red", overdue_tasks=2, gap_points=30.0, hours_used=70, hours_used_pct=70),
        proj("PL-B", ["JHS9001"], "green"),
        proj("PL-C", ["JHS9002"], "amber", days_since_last_entry=20),
        proj("PL-D", ["JHS9001", "JHS9002"], "amber", forecast_end="2026-11-05"),
        proj("PL-A", ["JHS9001"], "green", date="2026-10-14")])                         # older snapshot: must be ignored
    mdb["m_daily"].insert_many([
        daily("2026-10-13", "JHS9001", 2, 2, 4, 1, {"matched": 2}),
        daily("2026-10-14", "JHS9001", 2, 1, 2, 0, {"matched": 1, "short": 1}),
        daily("2026-10-14", "JHS9002", 1, 0, 0, 0, {}, size=1),
        daily("2026-09-01", "JHS9001", 2, 0, 0, 0, {})])                                 # outside the 10-day window
    mdb["m_team"].insert_many([team("JHS9101", "JHS9001", 180.0, 3), team("JHS9102", "JHS9001", 50.0, 0),
                               team("JHS9103", "JHS9002", 130.0, 1), team("JHS9101", "JHS9001", 10.0, 0, day="2026-10-14")])
    app = FastAPI()
    app.include_router(dr.router)
    app.dependency_overrides[get_current_user] = lambda: _user["id"]
    _user["id"] = "JHS9001"
    c = TestClient(app)
    c.db = mdb
    return c


def codes(resp):
    return [p["project_code"] for p in resp.json()["projects"]]


# ── access flags ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("user,flags", [
    ("JHS9001", {"is_admin": False, "is_partner": False, "is_manager": True, "manager_dashboard": True, "portfolio": False}),
    ("JHS9000", {"is_admin": True, "is_partner": False, "is_manager": True, "manager_dashboard": True, "portfolio": True}),
    ("JHS9050", {"is_admin": False, "is_partner": True, "is_manager": False, "manager_dashboard": True, "portfolio": True}),
    ("JHS9101", {"is_admin": False, "is_partner": False, "is_manager": False, "manager_dashboard": False, "portfolio": False}),
])
def test_access_flags(api, user, flags):
    _user["id"] = user
    assert api.get("/dashboard/access").json() == flags


# ── manager dashboard scoping ────────────────────────────────────────────────

def test_manager_sees_only_own_projects_worst_first(api):
    r = api.get("/dashboard/manager")
    assert r.status_code == 200
    assert codes(r) == ["PL-A", "PL-D", "PL-B"]                         # red, amber, green; PL-C belongs to the other manager
    assert r.json()["as_of"] == "2026-10-15"                            # latest snapshot only (not the 10-14 one)
    assert r.json()["projects"][0]["rag"] == "red"


def test_manager_kpis_team_load_and_alerts(api):
    body = api.get("/dashboard/manager").json()
    k = body["kpis"]
    assert (k["active_projects"], k["overdue_tasks"]) == (3, 2)
    assert (k["compliance_pct"], k["unplanned_pct"], k["reco_matched_pct"]) == (75.0, 16.7, 75.0)   # 3/4, 1/6, 3/4 (old row excluded)
    assert [t["employee_id"] for t in body["team_load"]] == ["JHS9101", "JHS9102"]                 # own team only, heaviest first
    assert body["team_load"][0]["load_pct"] == 180.0                                                # latest snapshot, not the 10-14 one
    texts = [a["text"] for a in body["alerts"]]
    assert any("PL-A" in t and "red" in t and "2 overdue" in t for t in texts)
    assert any("3 working days" in t for t in texts) and any("180.0% load" in t for t in texts)
    assert all("JHS9103" not in t and "PL-C" not in t for t in texts)
    assert body["notes"]["hours_include_legacy"] is True and body["notes"]["allocation_assumed_100"] is True


def test_other_manager_sees_their_own_data_only(api):
    _user["id"] = "JHS9002"
    r = api.get("/dashboard/manager")
    assert codes(r) == ["PL-C", "PL-D"] or codes(r) == ["PL-D", "PL-C"]
    assert [t["employee_id"] for t in r.json()["team_load"]] == ["JHS9103"]
    assert r.json()["kpis"]["compliance_pct"] == 0.0


def test_manager_cannot_view_someone_elses_dashboard(api):
    assert api.get("/dashboard/manager?manager=JHS9002").status_code == 403
    assert api.get("/dashboard/manager?manager=jhs9002").status_code == 403
    assert api.get('/dashboard/manager?manager={"$ne":""}').status_code == 403      # operator-looking input is just a string


def test_employee_and_unknown_users_have_no_dashboard(api):
    for u in ("JHS9101", "JHS9200", "JHS0000"):
        _user["id"] = u
        assert api.get("/dashboard/manager").status_code == 403
        assert api.get("/dashboard/portfolio").status_code == 403


def test_admin_and_partner_may_view_any_manager(api):
    for u in ("JHS9000", "JHS9050"):
        _user["id"] = u
        assert codes(api.get("/dashboard/manager?manager=JHS9002")) in (["PL-C", "PL-D"], ["PL-D", "PL-C"])
        assert api.get("/dashboard/manager?manager=JHS9001").json()["kpis"]["active_projects"] == 3
    _user["id"] = "JHS9000"
    assert api.get("/dashboard/manager").status_code == 200                          # admin without ?manager= sees their own (empty)


def test_window_bounds(api):
    assert api.get("/dashboard/manager?days=0").status_code == 422
    assert api.get("/dashboard/manager?days=91").status_code == 422
    short = api.get("/dashboard/manager?days=1").json()                              # only 2026-10-15: no rows
    assert short["kpis"]["compliance_pct"] is None


# ── portfolio ────────────────────────────────────────────────────────────────

def test_portfolio_roles(api):
    assert api.get("/dashboard/portfolio").status_code == 403                        # a manager is not enough
    for u in ("JHS9000", "JHS9050"):
        _user["id"] = u
        assert api.get("/dashboard/portfolio").status_code == 200


def test_portfolio_content(api):
    _user["id"] = "JHS9050"
    b = api.get("/dashboard/portfolio").json()
    k = b["kpis"]
    assert (k["projects"], k["red"], k["amber"], k["green"], k["overdue_tasks"]) == (4, 1, 2, 1, 2)
    assert k["hours_used"] == 190.0 and k["compliance_pct"] == 60.0                 # 3 of 5 expected days submitted
    assert [p["project_code"] for p in b["at_risk_projects"]][0] == "PL-A" and len(b["at_risk_projects"]) == 3
    d = next(p for p in b["at_risk_projects"] if p["project_code"] == "PL-D")
    assert d["days_late_forecast"] == 5 and d["manager_names"] == ["Manager A", "Manager B"]
    comp = b["compliance_by_manager"]
    assert [c["manager_id"] for c in comp] == ["JHS9002", "JHS9001"]                 # worst compliance first
    assert comp[0]["compliance_pct"] == 0.0 and comp[1]["compliance_pct"] == 75.0 and comp[1]["team_size"] == 2


def test_empty_data_does_not_break_the_dashboards(api):
    for coll in ("m_projects", "m_daily", "m_team"):
        api.db[coll].delete_many({})
    m = api.get("/dashboard/manager").json()
    assert m["as_of"] is None and m["projects"] == [] and m["team_load"] == [] and m["kpis"]["compliance_pct"] is None
    _user["id"] = "JHS9000"
    p = api.get("/dashboard/portfolio").json()
    assert p["kpis"]["projects"] == 0 and p["at_risk_projects"] == []


def test_dashboards_never_query_nq_or_raw_entries(api, monkeypatch):
    monkeypatch.setattr(repository, "_run", lambda *a, **k: pytest.fail("dashboard queried NQ"))
    api.db["c_entries"].drop()                                                       # raw entries are not needed either
    assert api.get("/dashboard/manager").status_code == 200
    _user["id"] = "JHS9000"
    assert api.get("/dashboard/portfolio").status_code == 200
