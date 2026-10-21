"""
The EXISTING timesheet grid now takes its clients / projects / activities from Nexus Quant.
Pure logic tests need nothing; endpoint and submit tests need the Docker dev stack
(Mongo 27018 scratch db 'timesnap_test', seeded fake NQ MySQL 3308).
Seed facts: JHS9101 = NQ user 3 -> tasks 1,2,3,4 (PL-T001) and 5 (PL-T002), all client 'Test Client A'.
"""
import os
import socket
from datetime import date

import pytest

os.environ.setdefault("MONGO_CONNECTION_STRING", "mongodb://localhost:27018/")

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pymongo import MongoClient

from backend.auth import get_current_user
from backend.nq import cache, repository
from backend.nq.models import NQTask
from backend.timesheet import nq_assignments as na
from backend.timesheet import router as tr
from tests.nq.conftest import DEV_PORT, dev_settings, nq_db, nq_down  # noqa: F401  (fixtures)

MONGO_PORT = int(os.getenv("MONGO_DEV_PORT", "27018"))


def task(tid, name, code="PL-1", project="Proj", client="Client", uid="", start=None, end=None, done=False, parent=None):
    return NQTask(id=tid, task_uid=uid, project_id=1, project_code=code, project_name=project, client_name=client,
                  name=name, start_date=start, end_date=end, is_complete=done, parent_task_id=parent)


# ── pure logic ───────────────────────────────────────────────────────────────

def test_view_groups_clients_projects_activities_and_keeps_labels_unique():
    tasks = [task(1, "Fieldwork", "PL-1", "Audit", "Beta", uid="T-001", start=date(2026, 10, 1), end=date(2026, 10, 9)),
             task(2, "Fieldwork", "PL-1", "Audit", "Beta", uid="T-002", start=date(2026, 10, 10), end=date(2026, 10, 20)),
             task(3, "Review", "PL-2", "Audit", "Beta"),                            # same project NAME, other code
             task(4, "Tax", "PL-3", "Tax", "alpha", parent=1)]
    v = na.build_assignment_view(tasks)
    assert v["clients"] == ["alpha", "Beta"]                                        # case-insensitive order
    assert [p["project_name"] for p in v["projects_by_client"]["Beta"]] == ["Audit (PL-1)", "Audit (PL-2)"]
    assert [p["project_code"] for p in v["projects_by_client"]["alpha"]] == ["PL-3"]
    assert [a["label"] for a in v["activities_by_project"]["PL-1"]] == ["Fieldwork (T-001)", "Fieldwork (T-002)"]
    assert v["activities_by_project"]["PL-2"][0]["label"] == "Review"
    assert v["activities_by_project"]["PL-3"][0]["parent_task_id"] == 1
    assert v["activities_by_project"]["PL-1"][1]["start_date"] == "2026-10-10"


def test_view_of_nothing_is_empty():
    assert na.build_assignment_view([]) == {"clients": [], "projects_by_client": {}, "activities_by_project": {}}


OFF = {"Leave", "PHY", "Week Off"}


def row(**kw):
    base = {"location": "Office", "client": "Client", "projectCode": "PL-1", "activity": "Fieldwork", "nqTaskId": 1}
    base.update(kw)
    return base


def test_activity_rules():
    assigned = {1: task(1, "Fieldwork", "PL-1"), 2: task(2, "Other task", "PL-2")}
    assert na.activity_errors([row()], assigned, OFF) == []
    assert na.activity_errors([row(nqTaskId="1")], assigned, OFF) == []                       # numeric string is fine
    assert "pick one of your assigned" in na.activity_errors([row(nqTaskId=None)], assigned, OFF)[0]
    assert "pick one of your assigned" in na.activity_errors([row(nqTaskId=99)], assigned, OFF)[0]
    assert "pick one of your assigned" in na.activity_errors([row(nqTaskId="abc")], assigned, OFF)[0]
    assert "does not belong to project PL-9" in na.activity_errors([row(projectCode="PL-9")], assigned, OFF)[0]
    assert na.activity_errors([row(projectCode="pl-1 ")], assigned, OFF) == []                # case / spaces tolerated
    assert na.activity_errors([row(nqTaskId=None, location="Leave")], assigned, OFF) == []    # day off: nothing needed
    assert na.activity_errors([row(nqTaskId=None, client="Other")], assigned, OFF) == []      # existing client "Other" behaviour
    other = row(nqTaskId=None, activityOther=True, activity="Client call", activityReason="Not planned in NQ")
    assert na.activity_errors([other], assigned, OFF) == []
    assert "give a reason" in na.activity_errors([{**other, "activityReason": " "}], assigned, OFF)[0]
    assert "give a reason" in na.activity_errors([{**other, "activityReason": "ab"}], assigned, OFF)[0]
    assert "describe the other activity" in na.activity_errors([{**other, "activity": ""}], assigned, OFF)[0]
    errs = na.activity_errors([row(), row(nqTaskId=None), row(nqTaskId=None)], assigned, OFF)
    assert [e.split(":")[0] for e in errs] == ["Row 2", "Row 3"]                              # row numbers are 1-based


# ── endpoint + submit gate against Docker Mongo + seeded NQ ──────────────────

def _up(port):
    s = socket.socket()
    s.settimeout(1)
    try:
        return s.connect_ex(("127.0.0.1", port)) == 0
    finally:
        s.close()


needs_stack = pytest.mark.skipif(not (_up(MONGO_PORT) and _up(DEV_PORT)),
                                 reason="Docker dev stack not running (docker compose -f docker-compose.dev.yml up -d)")
_user = {"id": "JHS9101"}


@pytest.fixture
def api(monkeypatch):
    if not (_up(MONGO_PORT) and _up(DEV_PORT)):
        pytest.skip("Docker dev stack not running")
    db = MongoClient(f"mongodb://127.0.0.1:{MONGO_PORT}/")["timesnap_test"]
    names = {"employee_details_collection": "g_employees", "timesheet_temp_collection": "g_temp",
             "timesheets_collection": "g_data", "pending_collection": "g_pending", "approved_collection": "g_approved",
             "rejected_collection": "g_rejected", "reporting_managers_collection": "g_managers",
             "approval_history_collection": "g_history"}
    for attr, coll in names.items():
        db[coll].drop()
        monkeypatch.setattr(tr, attr, db[coll])
    db["g_config"].drop()
    db["g_projects"].drop()
    db["g_plans"].drop()
    for coll in ("Projects", "Project_Plans", "Project Plans", "config"):                     # legacy lookups stay empty
        pass

    class _Db:                                                  # the router's `db` handle -> scratch collections
        def __getitem__(self, name):
            return db["g_" + name.lower().replace(" ", "_")]
    monkeypatch.setattr(tr, "db", _Db())
    import backend.database as bdb
    monkeypatch.setattr(bdb, "payroll_cycles_collection", db["g_cycles"])
    db["g_cycles"].drop()
    db["g_employees"].insert_many([
        {"EmpID": "JHS9101", "Emp Name": "Emp One", "PartnerEmpCode": "JHS02", "ReportingEmpCode": "JHS9001", "ReportingEmpName": "Mgr"},
        {"EmpID": "JHS9102", "Emp Name": "Emp Two", "PartnerEmpCode": "JHS02"},
        {"EmpID": "JHS9103", "Emp Name": "Emp Three", "PartnerEmpCode": "JHS02"},
        {"EmpID": "JHS9104", "Emp Name": "Emp Four", "PartnerEmpCode": "JHS02"},
        {"EmpID": "JHS9105", "Emp Name": "Shared Services", "PartnerEmpCode": "JHS01"},    # free-text partner
        {"EmpID": "JHS1562", "Emp Name": "Exempt Person", "PartnerEmpCode": "JHS02"}])     # free-text employee
    repository.configure(dev_settings())
    app = FastAPI()
    app.include_router(tr.router)
    app.dependency_overrides[get_current_user] = lambda: _user["id"]
    _user["id"] = "JHS9101"
    c = TestClient(app)
    c.db = db
    yield c
    repository.configure(dev_settings())
    cache.clear()


def projects(c, emp=None):
    return c.get(f"/timesheet/projects/{emp or _user['id']}")


@needs_stack
def test_employee_sees_only_what_is_assigned_in_nq(api):
    r = projects(api)
    assert r.status_code == 200
    b = r.json()
    assert b["source"] == "nq" and b["clients"] == ["Test Client A"] and b["partner_emp_code"] == "JHS02"
    codes = [p["project_code"] for p in b["projects_by_client"]["Test Client A"]]
    assert codes == ["PL-T002", "PL-T001"]                                                  # by project name: Internal..., Statutory...
    names = {p["project_code"]: p["project_name"] for p in b["projects_by_client"]["Test Client A"]}
    assert names == {"PL-T001": "Statutory Audit FY26", "PL-T002": "Internal Audit Q2"}
    # ordered by task start date, then name: 1, 3 and 4 start 10-01 (Overdue..., Overdue..., Planning...), 2 starts 10-12
    assert sorted(a["task_id"] for a in b["activities_by_project"]["PL-T001"]) == [1, 2, 3, 4]
    assert [a["task_id"] for a in b["activities_by_project"]["PL-T001"]][-1] == 2
    assert [a["task_id"] for a in b["activities_by_project"]["PL-T002"]] == [5]
    # not offered: task 12 (deleted project), 13 (assigned to someone else), PL-T003 / PL-T006 (not theirs), closed/deleted projects
    assert set(b["activities_by_project"]) == {"PL-T001", "PL-T002"}
    done = next(a for a in b["activities_by_project"]["PL-T001"] if a["task_id"] == 4)
    assert done["is_complete"] is True and done["end_date"] == "2026-10-05"                  # recently finished: still selectable


@needs_stack
def test_comma_separated_assignees_and_subtasks_and_other_clients(api):
    _user["id"] = "JHS9102"                                   # NQ user 4: tasks 5, 6 ('4, 5') and sub-task 9 (client B)
    b = projects(api).json()
    assert b["clients"] == ["Test Client A", "Test Client B"]
    assert sorted(a["task_id"] for a in b["activities_by_project"]["PL-T002"]) == [5, 6]
    sub = b["activities_by_project"]["PL-T003"]
    assert [a["task_id"] for a in sub] == [9] and sub[0]["parent_task_id"] == 5
    _user["id"] = "JHS9103"                                   # task 11 has no dates, task 10 starts later: both still open
    b = projects(api).json()
    assert sorted(a["task_id"] for a in b["activities_by_project"]["PL-T003"]) == [10, 11]
    _user["id"] = "JHS9104"                                   # a task ON HOLD is still open work
    assert [a["task_id"] for a in projects(api).json()["activities_by_project"]["PL-T003"]] == [14]


@needs_stack
def test_unknown_employee_and_other_peoples_data(api):
    api.db["g_employees"].insert_one({"EmpID": "JHS0000", "Emp Name": "Nobody Assigned", "PartnerEmpCode": "JHS02"})
    _user["id"] = "JHS0000"
    b = projects(api).json()
    assert b["clients"] == [] and b["activities_by_project"] == {} and b["nq_unavailable"] is False
    _user["id"] = "JHS9101"
    assert projects(api, "JHS9102").status_code == 403                                       # cannot read someone else's list
    _user["id"] = "JHS7777"                                                                  # not in Employee_details at all
    assert projects(api).json()["clients"] == []


@needs_stack
def test_free_text_employees_never_touch_nq(api, monkeypatch):
    monkeypatch.setattr(repository, "_run", lambda *a, **k: pytest.fail("NQ must not be queried for free-text employees"))
    for emp, partner in (("JHS9105", "JHS01"), ("JHS1562", "JHS02")):
        _user["id"] = emp
        b = projects(api).json()
        assert b["source"] == "free_text" and b["clients"] == [] and b["partner_emp_code"] == partner


@needs_stack
def test_nq_down_gives_an_empty_list_and_a_flag_not_an_error(api, nq_down):
    b = projects(api)
    assert b.status_code == 200 and b.json()["nq_unavailable"] is True and b.json()["clients"] == []


@needs_stack
def test_old_mongo_projects_collection_is_no_longer_used(api):
    api.db["g_projects"].insert_one({"client_name": "Legacy Client", "project_name": "Legacy", "project_code": "PL-OLD"})
    assert "Legacy Client" not in projects(api).json()["clients"]


@needs_stack
def test_project_plan_means_the_project_has_nq_tasks(api):
    has_plan, start, end = tr._lookup_project_plan("PL-T001")
    assert has_plan is True and start == date(2026, 10, 1) and end == date(2026, 10, 31)
    assert tr._lookup_project_plan("pl-t002")[0] is True                                       # case-insensitive
    assert tr._lookup_project_plan("PL-NOPE") == (False, None, None)                           # unknown: legacy fallback finds nothing
    assert tr._lookup_project_plan("") == (False, None, None)


@needs_stack
def test_project_plan_falls_back_when_nq_is_down(api, nq_down):
    assert tr._lookup_project_plan("PL-T001") == (False, None, None)                           # legacy lookup (empty here), no crash


# ── submit gate ──────────────────────────────────────────────────────────────

def entry(**kw):
    base = {"date": "2026-10-14", "location": "Office", "projectStartTime": "09:00", "projectEndTime": "18:00",
            "client": "Test Client A", "project": "Statutory Audit FY26", "projectCode": "PL-T001",
            "reportingManagerEntry": "Mgr", "activity": "Planning and scoping", "projectHours": "8", "billable": "Yes",
            "lunchTime": "30 min", "travelTime": "", "remarks": "", "nqTaskId": 1}
    base.update(kw)
    return base


def submit(api, entries):
    r = api.post("/timesheet/save-draft", json={"cycle_id": "c1", "cycle_label": "Test", "entries": entries, "metadata": {}})
    assert r.status_code == 200, r.text
    return api.post("/timesheet/submit", json={"cycle_id": "c1", "cycle_label": "Test"})


@needs_stack
def test_submit_accepts_assigned_activity(api):
    r = submit(api, [entry()])
    assert r.status_code == 200 and r.json()["success"] is True
    saved = api.db["g_data"].find_one({"employeeId": "JHS9101"})["payrolls"][0]["entries"][0]
    assert saved["nqTaskId"] == 1 and saved["activity"] == "Planning and scoping"             # task id travels with the entry


@needs_stack
@pytest.mark.parametrize("bad,expect", [
    ({"nqTaskId": None}, "pick one of your assigned activities"),
    ({"nqTaskId": 13}, "pick one of your assigned activities"),                               # assigned to someone else
    ({"nqTaskId": 5}, "does not belong to project"),                                          # task of another project code
    ({"nqTaskId": None, "activityOther": True, "activityReason": ""}, "give a reason"),
])
def test_submit_rejects_unassigned_or_unexplained_activity(api, bad, expect):
    r = submit(api, [entry(**bad)])
    assert r.status_code == 400 and expect in r.json()["detail"] and "Row 1" in r.json()["detail"]
    assert api.db["g_data"].count_documents({}) == 0                                          # nothing was published


@needs_stack
def test_submit_accepts_other_with_a_reason_and_skips_day_off_rows(api):
    other = entry(nqTaskId=None, activityOther=True, activityReason="Urgent client call, not in NQ",
                  activity="Client call", client="Test Client A")
    leave = entry(date="2026-10-15", location="Leave", nqTaskId=None, client="", project="", projectCode="",
                  activity="", lunchTime="", projectStartTime="", projectEndTime="", reportingManagerEntry="")
    assert submit(api, [other, leave]).status_code == 200


@needs_stack
def test_free_text_employees_are_exempt_from_the_activity_rule(api):
    _user["id"] = "JHS1562"
    api.db["g_employees"].update_one({"EmpID": "JHS1562"}, {"$set": {"ReportingEmpCode": "JHS9001"}})
    r = submit(api, [entry(projectCode="PL-ANY", nqTaskId=None, activity="Typed by hand")])
    assert r.status_code == 200


@needs_stack
def test_the_rule_can_be_switched_off_in_config(api):
    api.db["g_config"].insert_one({"_id": "timesheet", "nq_activity_required": False})
    assert submit(api, [entry(nqTaskId=None, activity="Legacy free text")]).status_code == 200


@needs_stack
def test_submit_reports_nq_outage_instead_of_guessing(api, nq_down):
    r = submit(api, [entry()])
    assert r.status_code == 503 and "unavailable" in r.json()["detail"]


@needs_stack
def test_editing_a_submitted_entry_cannot_bypass_the_rule(api):
    assert submit(api, [entry()]).status_code == 200
    eid = api.db["g_data"].find_one({"employeeId": "JHS9101"})["payrolls"][0]["entries"][0]["id"]
    ok = api.put(f"/timesheet/update/JHS9101/{eid}", json={"date": "2026-10-14", "activity": "Fieldwork week 2", "nqTaskId": 2})
    assert ok.status_code == 200
    bad = api.put(f"/timesheet/update/JHS9101/{eid}", json={"date": "2026-10-14", "activity": "Made up", "nqTaskId": 13})
    assert bad.status_code == 400
    assert api.db["g_data"].find_one({"employeeId": "JHS9101"})["payrolls"][0]["entries"][0]["activity"] == "Fieldwork week 2"
    plain = api.put(f"/timesheet/update/JHS9101/{eid}", json={"date": "2026-10-14", "remarks": "just a note"})   # activity untouched
    assert plain.status_code == 200
