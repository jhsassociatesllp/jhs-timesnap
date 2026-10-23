"""Admin data export (Excel / CSV). Scratch Mongo only. Admins only; every export is audited."""
import csv
import io
from datetime import datetime

import openpyxl
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.auth import get_current_user
from backend.metrics import access, admin_exports as ax
from backend.metrics.store import mstore
from tests.cycle.conftest import entry

_user = {"id": "JHS9000"}


@pytest.fixture
def api(cdb, monkeypatch):
    cdb["c_audit"].drop()
    monkeypatch.setattr(mstore, "audit", cdb["c_audit"])
    monkeypatch.setattr(access, "has_admin_module", lambda emp, key: emp == "JHS9000" and key == "timesheet")
    now = datetime.utcnow()
    cdb["c_entries"].insert_many([
        entry("JHS9101", "2026-10-12", 8.5, client="Client A", project="Audit", remarks="=HYPERLINK(\"http://x\")"),
        entry("JHS9101", "2026-10-13", 4, is_unplanned=True, task_id=None, task_name="", remarks="call"),
        entry("JHS9102", "2026-10-12", 7, client="Client B", project="Tax"),
        entry("JHS9101", "2026-09-22", 6, cycle_id="2026-09-C3")])
    cdb["c_submissions"].insert_many([
        {"employee_id": "JHS9101", "date": "2026-10-12", "location": "Office", "cycle_id": "2026-10-C2", "submitted_at": now}])
    cdb["c_reviews"].insert_one({"kind": "approval", "employee_id": "JHS9101", "cycle_id": "2026-10-C2", "status": "approved",
                                 "approved_by": "JHS9001", "approved_at": now, "history": [{"action": "approved"}],
                                 "mirror": {"status": "ok"}})
    cdb["c_hrms"].insert_one({"employee_id": "JHS9101", "date": "2026-10-12", "gross_hours": 9, "net_hours": 8.5, "leave_flag": False})
    cdb["c_reco"].insert_one({"employee_id": "JHS9101", "date": "2026-10-12", "result": "matched", "diff": 0})
    cdb["c_legacy"].insert_one({"employeeId": "JHS9101", "employeeName": "Emp One", "payrolls": [
        {"cycle_label": "Sep-Oct 2026", "approval_status": "approved", "entries": [
            {"date": "2026-10-12", "location": "Office", "client": "Client A", "project": "Audit", "projectCode": "PL1",
             "activity": "Fieldwork", "projectHours": "8.5", "v2_mirror": True},
            {"date": "2026-08-01", "projectHours": "5"}]}]})
    app = FastAPI()
    app.include_router(ax.router)
    app.dependency_overrides[get_current_user] = lambda: _user["id"]
    _user["id"] = "JHS9000"
    c = TestClient(app)
    c.db = cdb
    return c


def sheet(resp):
    ws = openpyxl.load_workbook(io.BytesIO(resp.content)).active
    return [[c for c in row] for row in ws.iter_rows(values_only=True)]


Q = "from=2026-10-01&to=2026-10-31"


def test_entries_export_has_payroll_cycle_names_and_neutralises_formulas(api):
    r = api.get(f"/admin-exports/entries?{Q}")
    assert r.status_code == 200 and r.headers["content-disposition"].endswith('.xlsx"')
    rows = sheet(r)
    assert rows[0][:6] == ["Employee ID", "Employee name", "Reporting manager", "Payroll", "Cycle", "Date"]
    assert len(rows) == 4                                                    # header + 3 October entries (September one is out)
    first = rows[1]
    assert first[0] == "JHS9101" and first[1] == "Emp One" and first[2] in ("", None) and first[3] == "2026-10" and first[4] == "2026-10-C2"
    assert str(first[13]).startswith("'=")                                   # =HYPERLINK(...) cannot run in Excel
    assert rows[0][13:15] == ["What I did", "Remarks"] and any(row[15] == "Yes" for row in rows[1:])      # the unplanned row


def test_filters_and_csv(api):
    r = api.get(f"/admin-exports/entries?{Q}&employee=jhs9102&format=csv")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    rows = list(csv.reader(io.StringIO(r.content.decode("utf-8-sig"))))
    assert len(rows) == 2 and rows[1][0] == "JHS9102"
    assert len(sheet(api.get("/admin-exports/entries?from=2026-09-01&to=2026-09-30"))) == 2


def test_cycle_summary_reviews_and_other_datasets(api):
    rows = sheet(api.get(f"/admin-exports/cycle-summary?{Q}"))
    one = next(r for r in rows[1:] if r[0] == "JHS9101")
    assert (one[3], one[4], one[5], one[6], one[7], one[8], one[9], one[10]) == ("2026-10", "2026-10-C2", 2, 2, 12.5, 1, "approved", "JHS9001")
    rev = sheet(api.get(f"/admin-exports/reviews?{Q}"))
    assert rev[1][4] == "approved" and rev[1][10] == 1 and rev[1][11] == "ok"
    for ds, col in (("submissions", "location"), ("hrms", "net_hours"), ("reco", "result")):
        r = sheet(api.get(f"/admin-exports/{ds}?{Q}"))
        assert col in r[0] and len(r) == 2
    cl = sheet(api.get(f"/admin-exports/classic?{Q}"))
    assert len(cl) == 2 and cl[1][4] == "2026-10-12" and cl[1][13].startswith("My day")        # August row is outside the range


def test_roles_validation_and_audit(api):
    assert api.get("/admin-exports/datasets").json()["datasets"][0]["id"] == "entries"
    api.get(f"/admin-exports/entries?{Q}&employee=JHS9101")
    log = api.db["c_audit"].find_one({"kind": "admin-export:entries"})
    assert log["by"] == "JHS9000" and log["rows"] == 2 and log["employees"] == ["JHS9101"]
    assert api.get("/admin-exports/export-log").status_code == 200
    assert api.get("/admin-exports/entries").status_code == 400                             # dates required
    assert api.get("/admin-exports/entries?from=2026-10-31&to=2026-10-01").status_code == 400
    assert api.get("/admin-exports/entries?from=2024-01-01&to=2026-10-01").status_code == 400
    assert api.get(f"/admin-exports/entries?{Q}&employee=JHS1;drop").status_code == 400
    assert api.get(f"/admin-exports/entries?{Q}&format=pdf").status_code == 400
    assert api.get(f"/admin-exports/nothing?{Q}").status_code == 404
    _user["id"] = "JHS9101"
    assert api.get("/admin-exports/datasets").status_code == 403
    assert api.get(f"/admin-exports/entries?{Q}").status_code == 403
    _user["id"] = "JHS9001"                                                                  # a manager is not enough
    assert api.get(f"/admin-exports/entries?{Q}").status_code == 403
