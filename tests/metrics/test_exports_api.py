import io
from datetime import datetime

import openpyxl
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.auth import get_current_user
from backend.metrics import access
from backend.metrics import exports as ex
from backend.metrics.store import mstore

ADMINS = {"JHS9000"}
_user = {"id": "JHS9050"}                         # a partner (Grade PND)
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def h(day, emp, code, hours, source="new", client="Client A", project="Project X"):
    return {"date": day, "employee_id": emp, "project_code": code, "client": client, "project": project,
            "hours": hours, "source": source, "updated_at": datetime.utcnow()}


@pytest.fixture
def api(mdb, monkeypatch):
    monkeypatch.setattr(mstore, "audit", mdb["m_audit"])
    mdb["m_audit"].drop()
    monkeypatch.setattr(access, "has_admin_module", lambda emp, key: emp in ADMINS and key == "timesheet")
    mdb["c_employees"].insert_one({"EmpID": "JHS9050", "Emp Name": "Partner P", "Grade Name": "PND", "ReportingEmpCode": ""})
    mdb["m_hours"].insert_many([
        h("2026-10-12", "JHS9101", "PL-A", 8, client="Client A"), h("2026-10-13", "JHS9101", "PL-A", 4, client="Client A"),
        h("2026-10-13", "JHS9101", "PL-B", 4, client="Client B", project="Project Y"),
        h("2026-10-12", "JHS9102", "PL-A", 7.5, source="legacy", client="Client A"),
        h("2026-09-25", "JHS9101", "PL-A", 8, client="Client A"),               # previous payroll cycle
        h("2026-11-25", "JHS9101", "PL-A", 8, client="Client A")])             # outside every range used below
    mdb["m_payroll_cycles"].insert_many([
        {"cycle_label": "Sep-Oct 2026", "start_date": "2026-09-21", "end_date": "2026-10-20"},
        {"cycle_label": "Oct-Nov 2026", "start_date": "2026-10-21", "end_date": "2026-11-20"},
        {"cycle_label": "Old", "start_date": "2025-01-21", "end_date": "2025-02-20"}])
    app = FastAPI()
    app.include_router(ex.router)
    app.dependency_overrides[get_current_user] = lambda: _user["id"]
    _user["id"] = "JHS9050"
    c = TestClient(app)
    c.db = mdb
    return c


def sheet(resp):
    assert resp.status_code == 200, resp.text
    ws = openpyxl.load_workbook(io.BytesIO(resp.content)).active
    rows = list(ws.iter_rows(values_only=True))
    return rows[0], rows[1:]


RANGE = "from=2026-09-21&to=2026-10-31"


# ── roles ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("path", ["project-hours", "client-allocation", "employee-projects"])
@pytest.mark.parametrize("user", ["JHS9001", "JHS9101", "JHS0000"])         # managers and employees are not enough
def test_only_partners_and_admins_can_export(api, path, user):
    _user["id"] = user
    assert api.get(f"/exports/{path}?{RANGE}").status_code == 403
    assert api.db["m_audit"].count_documents({}) == 0


@pytest.mark.parametrize("user", ["JHS9050", "JHS9000"])
def test_partner_and_admin_get_xlsx(api, user):
    _user["id"] = user
    r = api.get(f"/exports/project-hours?{RANGE}")
    assert r.status_code == 200 and r.headers["content-type"].startswith(XLSX)
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["content-disposition"] == 'attachment; filename="project-hours_2026-09-21_2026-10-31.xlsx"'


# ── content ──────────────────────────────────────────────────────────────────

def test_project_hours_totals_and_source_split(api):
    header, rows = sheet(api.get("/exports/project-hours?from=2026-10-01&to=2026-10-31"))
    assert header[:3] == ("Project code", "Project", "Client")
    got = {(r[0], r[3]): (r[5], r[6], r[7]) for r in rows}
    assert got == {("PL-A", "JHS9101"): (12.0, 12.0, 0.0), ("PL-A", "JHS9102"): (7.5, 0.0, 7.5),
                   ("PL-B", "JHS9101"): (4.0, 4.0, 0.0)}                    # September / November rows excluded


def test_employee_projects(api):
    _, rows = sheet(api.get("/exports/employee-projects?from=2026-10-01&to=2026-10-31"))
    a = next(r for r in rows if r[0] == "JHS9101" and r[2] == "PL-A")
    assert (a[5], a[6], a[7], a[8]) == (12.0, "2026-10-12", "2026-10-13", 2)


def test_client_allocation_per_payroll_cycle_with_percentages(api):
    header, rows = sheet(api.get(f"/exports/client-allocation?{RANGE}"))
    assert header[0] == "Payroll cycle" and header[-1] == "% of employee hours"
    got = {(r[0], r[3], r[5]): (r[6], r[7]) for r in rows}
    # cycle 1 (21 Sep - 20 Oct): JHS9101 = 8 (25 Sep, A) + 12 (A) + 4 (B); JHS9102 = 7.5 (A)
    assert got[("Sep-Oct 2026", "JHS9101", "Client A")] == (20.0, 83.3)
    assert got[("Sep-Oct 2026", "JHS9101", "Client B")] == (4.0, 16.7)
    assert got[("Sep-Oct 2026", "JHS9102", "Client A")] == (7.5, 100.0)
    assert all(r[0] != "Old" for r in rows) and all(r[0] != "Oct-Nov 2026" for r in rows)   # no hours in range for cycle 2
    pct = {}
    for (cyc, emp, _), (_, p) in got.items():
        pct[(cyc, emp)] = pct.get((cyc, emp), 0) + p
    assert all(abs(v - 100.0) < 0.2 for v in pct.values())


def test_client_allocation_clips_hours_to_the_requested_range(api):
    _, rows = sheet(api.get("/exports/client-allocation?from=2026-10-12&to=2026-10-12"))
    assert {(r[3], r[5], r[6]) for r in rows} == {("JHS9101", "Client A", 8.0), ("JHS9102", "Client A", 7.5)}
    assert api.get("/exports/client-allocation?from=2024-06-01&to=2024-06-30").status_code == 422   # no cycle there


# ── safety ───────────────────────────────────────────────────────────────────

def test_formula_injection_is_neutralised(api):
    api.db["m_hours"].insert_one(h("2026-10-14", "JHS9101", "=PL-EVIL", 1, client='=HYPERLINK("http://evil","x")',
                                   project="+cmd|' /C calc'!A0"))
    api.db["c_employees"].insert_one({"EmpID": "JHS9101", "Emp Name": "@SUM(1+1)", "ReportingEmpCode": ""})
    for path in ("project-hours", "employee-projects"):
        _, rows = sheet(api.get(f"/exports/{path}?from=2026-10-14&to=2026-10-14"))
        flat = [str(c) for r in rows for c in r if isinstance(c, str)]
        assert flat and not any(s.startswith(("=", "+", "-", "@")) for s in flat)
        assert any(s == "'=PL-EVIL" for s in flat) and any(s == "'@SUM(1+1)" for s in flat)
    assert ex.safe_cell("=1+1") == "'=1+1" and ex.safe_cell(5) == 5 and ex.safe_cell("ok") == "ok"
    assert ex.safe_cell("a\x00b\x07c") == "abc"


def test_range_validation_and_row_cap(api, monkeypatch):
    assert api.get("/exports/project-hours?from=2026-10-31&to=2026-10-01").status_code == 400
    assert api.get("/exports/project-hours?from=2025-01-01&to=2026-10-01").status_code == 400      # > 366 days
    assert api.get("/exports/project-hours?from=oops&to=2026-10-01").status_code == 400
    assert api.get("/exports/project-hours").status_code == 422
    monkeypatch.setattr(ex, "MAX_ROWS", 2)
    assert api.get("/exports/project-hours?from=2026-10-01&to=2026-10-31").status_code == 413


def test_export_refuses_to_read_an_enormous_source(api, monkeypatch):
    monkeypatch.setattr(ex, "MAX_SOURCE_ROWS", 3)                      # the fixture holds 6 hours rows
    for path in ("project-hours", "client-allocation", "employee-projects"):
        assert api.get(f"/exports/{path}?{RANGE}").status_code == 413
    assert api.db["m_audit"].count_documents({}) == 0


def test_every_export_is_audited(api):
    api.get("/exports/project-hours?from=2026-10-01&to=2026-10-31")
    _user["id"] = "JHS9000"
    api.get("/exports/employee-projects?from=2026-10-01&to=2026-10-31")
    rows = list(api.db["m_audit"].find({}, {"_id": 0, "at": 0}))
    assert rows == [{"kind": "project-hours", "by": "JHS9050", "from": "2026-10-01", "to": "2026-10-31", "rows": 3},
                    {"kind": "employee-projects", "by": "JHS9000", "from": "2026-10-01", "to": "2026-10-31", "rows": 3}]
