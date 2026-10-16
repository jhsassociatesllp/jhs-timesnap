from datetime import date

import pymysql
import pytest

from backend.nq import cache, repository
from backend.nq.models import NQUnavailable
from tests.nq.conftest import dev_settings

TODAY = date(2026, 10, 14)


def _ids(tasks):
    return sorted(t.id for t in tasks)


# ── reads against the seeded Docker MySQL ────────────────────────────────────

def test_tasks_for_employee_window_overdue_and_exclusions(nq_db):
    # JHS9101 = user 3: T1,T2 in window, T3 overdue+open, T5 shared ('3,4').
    # NOT: T4 (overdue but done), T12 (deleted project), T13 (assigned to '13', not '3'), T15 (done, old)
    assert _ids(nq_db.get_tasks_for_employee("JHS9101", TODAY)) == [1, 2, 3, 5]
    t3 = next(t for t in nq_db.get_tasks_for_employee("JHS9101", TODAY) if t.id == 3)
    assert t3.is_overdue and t3.project_code == "PL-T001"


def test_comma_and_space_separated_assignees_and_subtasks(nq_db):
    # JHS9102 = user 4: T5 ('3,4'), T6 ('4, 5'), T9 (sub-task); T8 is deleted.
    assert _ids(nq_db.get_tasks_for_employee("JHS9102", TODAY)) == [5, 6, 9]
    sub = nq_db.get_task(9)
    assert sub.parent_task_id == 5


def test_future_and_undated_tasks_not_listed(nq_db):
    # JHS9103 = user 5: T6 only; T10 starts later, T11 has no dates.
    assert _ids(nq_db.get_tasks_for_employee("JHS9103", TODAY)) == [6]


def test_unknown_or_deleted_employee_gets_nothing(nq_db):
    assert nq_db.get_tasks_for_employee("JHS0000", TODAY) == []
    assert nq_db.get_tasks_for_employee("JHS9199", TODAY) == []


def test_get_task_and_project(nq_db):
    assert nq_db.get_task(1).name == "Planning and scoping"
    assert nq_db.get_task(8) is None          # soft-deleted
    p = nq_db.get_project("PL-T001")
    assert p.project_name == "Statutory Audit FY26" and p.status == "active"
    assert nq_db.get_project("PL-T004") is None   # deleted project


def test_projects_for_manager_excludes_closed_deleted_and_other_managers(nq_db):
    codes = [p.project_code for p in nq_db.list_projects_for_manager("JHS9001")]
    assert codes == ["PL-T001", "PL-T002", "PL-T003"]   # T003 manager is '1,2'; T005 closed; T006 is '13'
    assert [p.project_code for p in nq_db.list_projects_for_manager("JHS9000")] == ["PL-T003"]


def test_assignments_for_project_expand_comma_lists(nq_db):
    a = nq_db.get_assignments_for_project("PL-T002")
    pairs = sorted((x.task_id, x.emp_id) for x in a)
    assert pairs == [(5, "JHS9101"), (5, "JHS9102"), (6, "JHS9102"), (6, "JHS9103")]
    assert all(x.allocation_pct == 100.0 for x in a)


def test_injection_string_is_just_data(nq_db):
    evil = "JHS9101' OR '1'='1"
    assert nq_db.get_tasks_for_employee(evil, TODAY) == []
    assert nq_db.get_project("PL-T001'; DROP TABLE tbl_projects;--") is None
    assert nq_db.get_project("PL-T001") is not None   # table still there


def test_second_call_served_from_cache(nq_db, monkeypatch):
    nq_db.get_task(1)
    monkeypatch.setattr(repository, "_run", lambda *a, **k: pytest.fail("hit MySQL again"))
    assert nq_db.get_task(1).id == 1


# ── write-back touches end_date only ─────────────────────────────────────────

def test_update_task_end_date_changes_only_end_date(nq_db):
    before = nq_db.get_task(2)
    try:
        assert nq_db.update_task_end_date(2, date(2026, 10, 30)) == 1
        after = nq_db.get_task(2)
        assert after.end_date == date(2026, 10, 30)
        assert after.model_dump(exclude={"end_date", "is_overdue"}) == \
               before.model_dump(exclude={"end_date", "is_overdue"})
    finally:
        nq_db.update_task_end_date(2, before.end_date)


def test_write_user_cannot_update_other_columns(nq_db):
    conn = pymysql.connect(host="127.0.0.1", port=dev_settings().port, user="nq_wb",
                           password="dev_wb_pass", database="jhsdb")
    with conn.cursor() as cur, pytest.raises(pymysql.err.OperationalError):
        cur.execute("UPDATE tbl_project_tasks SET task_name = 'x' WHERE id = 1")
    conn.close()


def test_read_user_cannot_write(nq_db):
    conn = pymysql.connect(host="127.0.0.1", port=dev_settings().port, user="nq_ro",
                           password="dev_ro_pass", database="jhsdb")
    with conn.cursor() as cur, pytest.raises(pymysql.err.OperationalError):
        cur.execute("UPDATE tbl_project_tasks SET end_date = '2030-01-01' WHERE id = 1")
    conn.close()


# ── NQ down (no Docker needed) ───────────────────────────────────────────────

def test_down_raises_nq_unavailable_when_nothing_cached(nq_down):
    with pytest.raises(NQUnavailable):
        nq_down.get_task(1)
    with pytest.raises(NQUnavailable):
        nq_down.ping()


def test_down_serves_stale_cache_and_flags_banner(nq_down):
    # seed the cache as if an earlier read had succeeded, then expire it
    key = ("task", 1)
    cache._store[key] = (-10_000.0, "cached-task")
    assert nq_down.get_task(1) == "cached-task"
    assert cache.data_may_be_stale()


def test_health_endpoint_reports_unreachable(nq_down):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.auth import get_current_user
    from backend.nq.health import router

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: "JHS9101"
    body = TestClient(app).get("/api/health/nq").json()
    assert body["reachable"] is False and body["latency_ms"] is None


def test_health_endpoint_reports_reachable(nq_db):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.auth import get_current_user
    from backend.nq.health import router

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: "JHS9101"
    body = TestClient(app).get("/api/health/nq").json()
    assert body["reachable"] is True and body["latency_ms"] is not None and body["last_success"]
