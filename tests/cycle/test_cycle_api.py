"""
Cycle review API tests. Mongo scratch db (27018) for timesheet data; seeded fake NQ MySQL (3308) for
the re-estimate / at-risk tests. 'Today' is pinned to 2026-10-14 (cycle 2026-10-C2: working days 12,13,14).
Seed NQ facts: PL-T001 (manager user 1 = JHS9001) has overdue open task 3 -> RED; PL-T002/PL-T003 are green.
"""
from datetime import date, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import mailer
from backend.auth import get_current_user
from backend.cycle import router as cr
from backend.nq import repository
from tests.cycle.conftest import DAY, entry
from tests.nq.conftest import dev_settings, nq_db  # noqa: F401  (fixture)

CYCLE = "2026-10-C2"
ADMINS = {"JHS9000"}
_user = {"id": "JHS9001"}


@pytest.fixture
def api(cdb, monkeypatch):
    monkeypatch.setattr(cr, "has_admin_module", lambda emp, key: emp in ADMINS and key == "timesheet")
    monkeypatch.setattr(cr, "_today", lambda: date(2026, 10, 14))
    app = FastAPI()
    app.include_router(cr.router)
    app.dependency_overrides[get_current_user] = lambda: _user["id"]
    _user["id"] = "JHS9001"
    c = TestClient(app)
    c.db = cdb
    return c


def seed_cycle(db):
    """JHS9101 fully submitted; JHS9102 submitted only the 12th and has an open hours gap;
    JHS9103 (other team) on leave the 13th."""
    now = datetime.utcnow()
    for day in ("2026-10-12", "2026-10-13", "2026-10-14"):
        db["c_submissions"].insert_one({"employee_id": "JHS9101", "date": day, "submitted_at": now})
        db["c_entries"].insert_one(entry("JHS9101", day, 8.5))
    db["c_submissions"].insert_one({"employee_id": "JHS9102", "date": "2026-10-12", "submitted_at": now})
    db["c_entries"].insert_many([entry("JHS9102", "2026-10-12", 5, is_unplanned=True, task_id=None),
                                 entry("JHS9102", "2026-10-13", 3)])
    for day in ("2026-10-12", "2026-10-13", "2026-10-14"):
        db["c_hrms"].insert_one({"employee_id": "JHS9101", "date": day, "net_hours": 8.5, "leave_flag": False})
    db["c_hrms"].insert_one({"employee_id": "JHS9102", "date": "2026-10-12", "net_hours": 7.0, "leave_flag": False})
    db["c_hrms"].insert_one({"employee_id": "JHS9103", "date": "2026-10-13", "net_hours": None, "leave_flag": True})
    db["c_reco"].insert_one({"employee_id": "JHS9102", "date": "2026-10-12", "result": "short",
                             "status": "open", "diff": -2.0})
    db["c_entries"].insert_one(entry("JHS9103", "2026-10-12", 8))
    db["c_submissions"].insert_one({"employee_id": "JHS9103", "date": "2026-10-12", "submitted_at": now})


def rows_by_emp(resp):
    return {r["employee_id"]: r for r in resp.json()["rows"]}


# ── team table + roles ───────────────────────────────────────────────────────

def test_team_table_figures(api):
    seed_cycle(api.db)
    r = api.get(f"/timesheet/v2/cycles/{CYCLE}/team")
    assert r.status_code == 200
    rows = rows_by_emp(r)
    assert set(rows) == {"JHS9101", "JHS9102"}                      # own pilot reportees only
    a, b = rows["JHS9101"], rows["JHS9102"]
    assert (a["days_required"], a["days_filled"], a["missing_dates"], a["warnings"]) == (3, 3, [], [])
    assert (a["hrms_hours"], a["timesheet_hours"], a["status"]) == (25.5, 25.5, "pending")
    assert (b["days_filled"], b["missing_dates"], b["unplanned"], b["reco_gaps"]) == (1, ["2026-10-13", "2026-10-14"], 1, 1)
    assert b["timesheet_hours"] == 8.0 and len(b["warnings"]) == 2
    assert r.json()["cycle"]["deadline"] == "2026-10-25" and r.json()["cycle"]["past_deadline"] is False


def test_leave_days_are_not_required(api):
    seed_cycle(api.db)
    _user["id"] = "JHS9002"
    row = rows_by_emp(api.get(f"/timesheet/v2/cycles/{CYCLE}/team"))["JHS9103"]
    assert row["days_required"] == 2 and row["missing_dates"] == ["2026-10-14"]     # the 13th is HRMS leave


def test_team_roles(api):
    seed_cycle(api.db)
    _user["id"] = "JHS9002"
    assert set(rows_by_emp(api.get(f"/timesheet/v2/cycles/{CYCLE}/team"))) == {"JHS9103"}
    _user["id"] = "JHS9101"                                                          # an employee
    assert api.get(f"/timesheet/v2/cycles/{CYCLE}/team").status_code == 403
    _user["id"] = "JHS9000"                                                          # admin sees everyone, can filter
    assert set(rows_by_emp(api.get(f"/timesheet/v2/cycles/{CYCLE}/team"))) == {"JHS9101", "JHS9102", "JHS9103"}
    assert set(rows_by_emp(api.get(f"/timesheet/v2/cycles/{CYCLE}/team?manager=JHS9002"))) == {"JHS9103"}
    _user["id"] = "JHS9001"                                                          # manager cannot widen with ?manager=
    assert set(rows_by_emp(api.get(f"/timesheet/v2/cycles/{CYCLE}/team?manager=JHS9002"))) == {"JHS9101", "JHS9102"}
    assert api.get("/timesheet/v2/cycles/2026-10-C9/team").status_code == 400


# ── approve and lock ─────────────────────────────────────────────────────────

def test_approve_clean_employee_locks_entries_and_cycle(api):
    seed_cycle(api.db)
    r = api.post(f"/timesheet/v2/cycles/{CYCLE}/approve", json={"employee_ids": ["jhs9101"]})
    assert r.status_code == 200 and r.json()["approved"] == ["JHS9101"]
    assert all(e["locked"] and e["approved"] and e["approved_by"] == "JHS9001"
               for e in api.db["c_entries"].find({"employee_id": "JHS9101"}))
    from backend.cycle.locks import cycle_locked
    assert cycle_locked("JHS9101", CYCLE) and not cycle_locked("JHS9102", CYCLE)
    assert rows_by_emp(api.get(f"/timesheet/v2/cycles/{CYCLE}/team"))["JHS9101"]["status"] == "approved"


def test_approve_with_open_items_needs_confirmation_and_changes_nothing_otherwise(api):
    seed_cycle(api.db)
    r = api.post(f"/timesheet/v2/cycles/{CYCLE}/approve", json={"employee_ids": ["JHS9101", "JHS9102"]})
    assert r.status_code == 409 and set(r.json()["detail"]["warnings"]) == {"JHS9102"}
    assert api.db["c_entries"].count_documents({"locked": True}) == 0                 # nobody was locked
    ok = api.post(f"/timesheet/v2/cycles/{CYCLE}/approve",
                  json={"employee_ids": ["JHS9101", "JHS9102"], "confirm_warnings": True})
    assert ok.status_code == 200 and ok.json()["warnings_confirmed"] == ["JHS9102"]
    review = api.db["c_reviews"].find_one({"employee_id": "JHS9102", "kind": "approval"})
    assert review["warnings_confirmed"] is True and review["history"][0]["warnings"]


def test_approve_authorisation_and_validation(api):
    seed_cycle(api.db)
    r = api.post(f"/timesheet/v2/cycles/{CYCLE}/approve", json={"employee_ids": ["JHS9101", "JHS9103"]})
    assert r.status_code == 403 and "JHS9103" in r.json()["detail"]                   # someone else's employee
    assert api.db["c_entries"].count_documents({"locked": True}) == 0                 # all-or-nothing
    assert api.post(f"/timesheet/v2/cycles/{CYCLE}/approve", json={"employee_ids": []}).status_code == 422
    assert api.post(f"/timesheet/v2/cycles/{CYCLE}/approve", json={"employee_ids": ["JHS9104"]}).status_code == 422
    api.db["c_entries"].delete_many({"employee_id": "JHS9101"})
    assert api.post(f"/timesheet/v2/cycles/{CYCLE}/approve", json={"employee_ids": ["JHS9101"]}).status_code == 422
    _user["id"] = "JHS9101"
    assert api.post(f"/timesheet/v2/cycles/{CYCLE}/approve", json={"employee_ids": ["JHS9101"]}).status_code == 403
    _user["id"] = "JHS9000"                                                           # admin may approve anyone
    assert api.post(f"/timesheet/v2/cycles/{CYCLE}/approve",
                    json={"employee_ids": ["JHS9103"], "confirm_warnings": True}).status_code == 200


# ── unlock ───────────────────────────────────────────────────────────────────

def test_only_admin_can_unlock_and_it_is_audited(api):
    seed_cycle(api.db)
    api.post(f"/timesheet/v2/cycles/{CYCLE}/approve", json={"employee_ids": ["JHS9101"]})
    body = {"employee_id": "JHS9101", "reason": "Wrong project on the 13th"}
    assert api.post(f"/timesheet/v2/cycles/{CYCLE}/unlock", json=body).status_code == 403    # their own manager
    _user["id"] = "JHS9101"
    assert api.post(f"/timesheet/v2/cycles/{CYCLE}/unlock", json=body).status_code == 403    # the employee
    _user["id"] = "JHS9000"
    assert api.post(f"/timesheet/v2/cycles/{CYCLE}/unlock", json={**body, "reason": "x"}).status_code == 422
    assert api.post(f"/timesheet/v2/cycles/{CYCLE}/unlock",
                    json={"employee_id": "JHS9102", "reason": "not approved at all"}).status_code == 404
    assert api.post(f"/timesheet/v2/cycles/{CYCLE}/unlock", json=body).status_code == 200
    assert not any(e["locked"] for e in api.db["c_entries"].find({"employee_id": "JHS9101"}))
    review = api.db["c_reviews"].find_one({"employee_id": "JHS9101"})
    assert review["status"] == "reopened" and [h["action"] for h in review["history"]] == ["approved", "unlocked"]
    assert review["history"][1]["reason"] == "Wrong project on the 13th"


# ── reminders ────────────────────────────────────────────────────────────────

@pytest.fixture
def mail(monkeypatch):
    sent = []
    monkeypatch.setenv("TIMESNAP_SEND_MAIL", "1")
    monkeypatch.setattr(mailer, "send_mail", lambda to, subject, text, body: (sent.append((to, subject, text, body)) or ("sent", "")))
    return sent


def test_remind_pending_once_per_day(api, mail):
    seed_cycle(api.db)
    body = {"employee_ids": ["JHS9101", "JHS9102"]}
    r = api.post(f"/timesheet/v2/cycles/{CYCLE}/remind", json=body).json()
    assert r["sent"] == ["JHS9102"] and r["skipped"] == [{"employee_id": "JHS9101", "reason": "nothing pending"}]
    assert mail[0][0] == ["e2@example.invalid"] and "2026-10-13" in mail[0][2]
    again = api.post(f"/timesheet/v2/cycles/{CYCLE}/remind", json=body).json()
    assert again["sent"] == [] and {"employee_id": "JHS9102", "status": "duplicate"} in again["skipped"]
    assert len(mail) == 1


def test_remind_roles_and_missing_email(api, mail):
    seed_cycle(api.db)
    assert api.post(f"/timesheet/v2/cycles/{CYCLE}/remind", json={"employee_ids": ["JHS9103"]}).status_code == 403
    _user["id"] = "JHS9102"
    assert api.post(f"/timesheet/v2/cycles/{CYCLE}/remind", json={"employee_ids": ["JHS9102"]}).status_code == 403
    _user["id"] = "JHS9001"
    api.db["c_employees"].update_one({"EmpID": "JHS9102"}, {"$set": {"EMail": ""}})
    r = api.post(f"/timesheet/v2/cycles/{CYCLE}/remind", json={"employee_ids": ["JHS9102"]}).json()
    assert r["sent"] == [] and r["skipped"][0]["reason"] == "no valid EMail" and not mail


def test_remind_does_not_send_when_mail_is_disabled(api, monkeypatch):
    seed_cycle(api.db)
    monkeypatch.delenv("TIMESNAP_SEND_MAIL", raising=False)
    monkeypatch.setattr(mailer, "send_mail", lambda *a: pytest.fail("must not be called"))
    r = api.post(f"/timesheet/v2/cycles/{CYCLE}/remind", json={"employee_ids": ["JHS9102"]}).json()
    assert r["sent"] == [] and r["skipped"] == [{"employee_id": "JHS9102", "status": "disabled"}]


# ── at-risk + re-estimate (needs the seeded NQ MySQL) ────────────────────────

def test_at_risk_lists_only_amber_red_projects_the_caller_manages(api, nq_db):
    r = api.get(f"/timesheet/v2/cycles/{CYCLE}/at-risk").json()
    assert [(p["project_code"], p["rag"]) for p in r["projects"]] == [("PL-T001", "red")]
    t = {x["task_id"]: x for x in r["projects"][0]["tasks"]}
    assert t[3]["is_overdue"] is True and 4 not in t                                  # done task is not offered
    assert r["writeback_enabled"] is False
    assert api.get(f"/timesheet/v2/cycles/{CYCLE}/at-risk?manager=JHS9002").status_code == 403
    _user["id"] = "JHS9000"
    assert api.get(f"/timesheet/v2/cycles/{CYCLE}/at-risk?manager=JHS9001").json()["projects"][0]["project_code"] == "PL-T001"
    _user["id"] = "JHS9101"
    assert api.get(f"/timesheet/v2/cycles/{CYCLE}/at-risk").json()["projects"] == []  # manages nothing


def _est(**kw):
    return {"task_id": 3, "hours_needed": 12, "new_end_date": "2026-10-30", "note": "client delay", **kw}


def test_reestimate_stores_record_without_writing_to_nq_by_default(api, nq_db):
    before = nq_db.get_task(3).end_date
    r = api.post(f"/timesheet/v2/cycles/{CYCLE}/reestimate", json=_est())
    assert r.status_code == 200 and r.json()["written_back"] is False and r.json()["writeback_enabled"] is False
    rec = api.db["c_reviews"].find_one({"kind": "reestimate"})
    assert (rec["task_id"], rec["old_end_date"], rec["new_end_date"], rec["requested_by"], rec["rag_at_time"]) == \
           (3, before.isoformat(), "2026-10-30", "JHS9001", "red")
    # read straight from MySQL (not the cache) to prove nothing was written:
    assert repository._run("SELECT end_date FROM tbl_project_tasks WHERE id=%s", (3,))[0]["end_date"] == before


def test_reestimate_rules_and_roles(api, nq_db):
    ep = f"/timesheet/v2/cycles/{CYCLE}/reestimate"
    assert api.post(ep, json=_est(task_id=4)).status_code == 404               # completed task
    assert api.post(ep, json=_est(task_id=99999)).status_code == 404
    assert api.post(ep, json=_est(new_end_date="2026-10-01")).status_code == 422          # in the past
    assert api.post(ep, json=_est(new_end_date="2031-01-01")).status_code == 422          # > 2 years
    assert api.post(ep, json=_est(hours_needed=-1)).status_code == 422
    _user["id"] = "JHS9002"                                                    # manages nothing
    assert api.post(ep, json=_est()).status_code == 403
    _user["id"] = "JHS9000"                                                    # admin, red project -> allowed
    assert api.post(ep, json=_est()).status_code == 200


def test_reestimate_on_green_project_is_rejected(api, nq_db):
    assert api.post(f"/timesheet/v2/cycles/{CYCLE}/reestimate", json=_est(task_id=5)).status_code == 422


def test_writeback_changes_only_end_date_and_only_when_enabled(api, nq_db):
    before = repository._run("SELECT task_name, start_date, end_date, assigned_to, task_status FROM tbl_project_tasks WHERE id=3")[0]
    api.db["c_config"].update_one({"_id": "timesheet"}, {"$set": {"nq_writeback_enabled": True}})
    try:
        r = api.post(f"/timesheet/v2/cycles/{CYCLE}/reestimate", json=_est(new_end_date="2026-11-05"))
        assert r.status_code == 200 and r.json()["written_back"] is True
        after = repository._run("SELECT task_name, start_date, end_date, assigned_to, task_status FROM tbl_project_tasks WHERE id=3")[0]
        assert str(after["end_date"]) == "2026-11-05"
        assert {k: v for k, v in after.items() if k != "end_date"} == {k: v for k, v in before.items() if k != "end_date"}
        assert api.db["c_reviews"].find_one({"kind": "reestimate"})["written_back"] is True
    finally:
        repository.update_task_end_date(3, before["end_date"])                # leave the seed as we found it


def test_writeback_failure_keeps_the_record(api, nq_db, monkeypatch):
    from backend.nq.models import NQUnavailable
    api.db["c_config"].update_one({"_id": "timesheet"}, {"$set": {"nq_writeback_enabled": True}})
    monkeypatch.setattr(repository, "update_task_end_date", lambda *a: (_ for _ in ()).throw(NQUnavailable("down")))
    r = api.post(f"/timesheet/v2/cycles/{CYCLE}/reestimate", json=_est())
    assert r.status_code == 200 and r.json()["written_back"] is False and r.json()["writeback_error"] == "down"
    assert api.db["c_reviews"].find_one({"kind": "reestimate"})["writeback_error"] == "down"
