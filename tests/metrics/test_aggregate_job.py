from datetime import date, datetime, timedelta

import pytest

from backend.jobs import scheduler
from backend.metrics import aggregate as agg
from backend.metrics import job
from backend.nq import repository
from backend.nq.models import NQUnavailable
from tests.metrics.conftest import entry

DAY = date(2026, 10, 15)         # job date (Thursday); snapshots describe the end of 2026-10-14


def hrows(db, **q):
    return {(r["date"], r["employee_id"], r["project_code"], r["source"]): r["hours"] for r in db["m_hours"].find(q)}


# ── hours_daily ──────────────────────────────────────────────────────────────

def test_hours_daily_combines_new_and_legacy_without_double_counting(mdb):
    mdb["c_entries"].insert_many([
        entry("JHS9101", "2026-10-12", 5, project_code="PL-T001"), entry("JHS9101", "2026-10-12", 3, project_code="PL-T001"),
        entry("JHS9101", "2026-10-13", 4, project_code="PL-T002"),
        entry("JHS9101", "2026-10-14", 8, project_code="PL-T001", legacy=True),          # migrated copy: ignored
        entry("JHS9102", "2026-10-12", None, project_code="PL-T001")])                   # awaiting HRMS: no hours
    mdb["m_legacy"].insert_many([
        {"employeeId": "jhs9105", "payrolls": [
            {"entries": [{"date": "2026-10-12", "projectCode": "pl-t001", "client": "C", "project": "P", "projectHours": "6"},
                         {"date": "2026-10-12", "projectCode": "PL-T001", "projectHours": "1.5"},
                         {"date": "2026-10-13", "location": "Leave", "projectHours": ""},
                         {"date": "2026-10-13", "projectCode": "PL-T001", "projectHours": "abc"}]},
            {"weeks": [{"entries": [{"date": "2026-10-14", "projectCode": "PL-T002", "projectHours": "4"}]}]}]},
        {"employeeId": "JHS9101", "payrolls": [{"entries": [
            {"date": "2026-10-12", "projectCode": "PL-T001", "projectHours": "8"},        # same day as NEW entries: skipped
            {"date": "2026-10-14", "projectCode": "PL-T001", "projectHours": "8"}]}]}])   # no new entry that day: counted
    agg.build_hours_daily()
    assert hrows(mdb) == {
        ("2026-10-12", "JHS9101", "PL-T001", "new"): 8.0,
        ("2026-10-13", "JHS9101", "PL-T002", "new"): 4.0,
        ("2026-10-12", "JHS9105", "PL-T001", "legacy"): 7.5,
        ("2026-10-14", "JHS9105", "PL-T002", "legacy"): 4.0,
        ("2026-10-14", "JHS9101", "PL-T001", "legacy"): 8.0}


def test_hours_daily_is_idempotent_and_removes_stale_rows(mdb):
    mdb["c_entries"].insert_many([entry("JHS9101", "2026-10-12", 5), entry("JHS9101", "2026-10-13", 4)])
    agg.build_hours_daily()
    first = hrows(mdb)
    agg.build_hours_daily()
    assert hrows(mdb) == first and mdb["m_hours"].count_documents({}) == 2
    mdb["c_entries"].delete_many({"date": "2026-10-13"})                       # source changed
    out = agg.build_hours_daily()
    assert out["removed"] == 1 and set(k[0] for k in hrows(mdb)) == {"2026-10-12"}


def test_incremental_rebuild_only_touches_the_window(mdb):
    mdb["c_entries"].insert_many([entry("JHS9101", "2026-08-01", 5), entry("JHS9101", "2026-10-12", 4)])
    agg.build_hours_daily()
    mdb["c_entries"].update_one({"date": "2026-08-01"}, {"$set": {"hours": 99}})     # old day edited...
    mdb["c_entries"].update_one({"date": "2026-10-12"}, {"$set": {"hours": 6}})
    agg.build_hours_daily(since=date(2026, 10, 1))                                   # ...but outside the window
    got = hrows(mdb)
    assert got[("2026-08-01", "JHS9101", "PL-T001", "new")] == 5.0 and got[("2026-10-12", "JHS9101", "PL-T001", "new")] == 6.0


def test_a_suddenly_empty_source_does_not_wipe_stored_hours(mdb):
    mdb["c_entries"].insert_many([entry("JHS9101", f"2026-09-{d:02d}", 4) for d in range(1, 26)])      # 25 stored rows
    agg.build_hours_daily()
    assert mdb["m_hours"].count_documents({}) == 25
    mdb["c_entries"].delete_many({})                                    # e.g. the job was pointed at the wrong database
    out = agg.build_hours_daily()
    assert out["removed"] == 0 and out["delete_skipped"] == 25
    assert mdb["m_hours"].count_documents({}) == 25                    # history kept
    mdb["c_entries"].insert_many([entry("JHS9101", f"2026-09-{d:02d}", 4) for d in range(1, 21)])      # a normal change: 5 of 25 vanish
    assert agg.build_hours_daily()["removed"] == 5


def test_empty_nq_result_keeps_the_last_good_snapshots(mdb):
    day = date(2026, 10, 15)
    mdb["m_projects"].insert_one({"date": "2026-10-15", "project_code": "PL-A", "rag": "red"})
    mdb["m_team"].insert_one({"date": "2026-10-15", "employee_id": "JHS9101", "load_pct": 10})
    mdb["m_daily"].insert_one({"date": "2026-10-15", "manager_id": "JHS9001"})
    assert agg.save_project_metrics(day, []) == 0 and agg.save_team_snapshot(day, []) == 0
    assert agg.save_dashboard_daily(day, []) == 0
    assert mdb["m_projects"].count_documents({}) == 1 and mdb["m_team"].count_documents({}) == 1
    assert mdb["m_daily"].count_documents({}) == 1


# ── project metrics ──────────────────────────────────────────────────────────

def test_job_builds_project_metrics_from_nq_and_hours(mdb, nq_db):
    mdb["c_entries"].insert_many([entry("JHS9101", "2026-10-12", 8.5, project_code="PL-T001"),
                                  entry("JHS9101", "2026-10-13", 8.5, project_code="PL-T001")])
    mdb["m_legacy"].insert_one({"employeeId": "JHS9105", "payrolls": [{"entries": [
        {"date": "2026-10-14", "projectCode": "PL-T001", "projectHours": "10"}]}]})
    stats = job.run(DAY)
    assert stats["projects"] == 4
    p = {d["project_code"]: d for d in mdb["m_projects"].find({"date": "2026-10-15"})}
    t1 = p["PL-T001"]
    assert (t1["tasks_total"], t1["tasks_done"], t1["tasks_done_pct"], t1["overdue_tasks"]) == (4, 1, 25.0, 1)
    assert t1["budget_hours"] == 289.0                                     # holiday 10-02 removed from 3 assignments
    assert (t1["hours_used"], t1["hours_new"], t1["hours_legacy"]) == (27.0, 17.0, 10.0)
    assert t1["rag"] == "red" and t1["manager_emp_ids"] == ["JHS9001"] and t1["partner_emp_id"] == "JHS9000"
    assert t1["days_since_last_entry"] == 1 and t1["planned_end"] == "2026-10-31"
    assert p["PL-T002"]["rag"] == "green" and p["PL-T002"]["hours_used"] == 0.0
    assert "PL-T004" not in p and "PL-T005" not in p                       # deleted / closed projects


def test_job_is_idempotent_and_drops_projects_that_are_no_longer_active(mdb, nq_db):
    job.run(DAY)
    first = mdb["m_projects"].count_documents({"date": "2026-10-15"})
    job.run(DAY)
    assert mdb["m_projects"].count_documents({"date": "2026-10-15"}) == first == 4
    mdb["m_projects"].insert_one({"date": "2026-10-15", "project_code": "PL-OLD", "rag": "red"})
    job.run(DAY)
    assert mdb["m_projects"].count_documents({"project_code": "PL-OLD"}) == 0
    assert mdb["m_team"].count_documents({"date": "2026-10-15", "employee_id": "JHS9101"}) == 1


# ── team snapshot ────────────────────────────────────────────────────────────

def test_team_load_remaining_hours_over_capacity(mdb, nq_db):
    job.run(DAY)
    t = mdb["m_team"].find_one({"date": "2026-10-15", "employee_id": "JHS9101"})
    # due-or-overdue open tasks of user 3 within the next 10 working days (to 10-28):
    # T2 42.5 + T3 (overdue) 51 + T5 59.5; T1 ends 10-31 (outside window), T4 is done
    assert t["remaining_hours"] == 153.0 and t["capacity_hours"] == 85.0 and t["load_pct"] == 180.0
    assert t["open_tasks"] == 3 and t["window_end"] == "2026-10-28" and t["manager_id"] == "JHS9001"


def test_hours_already_logged_on_a_task_reduce_the_load(mdb, nq_db):
    mdb["c_entries"].insert_one(entry("JHS9101", "2026-10-12", 20, task_id=3, project_code="PL-T001"))
    job.run(DAY)
    t = mdb["m_team"].find_one({"employee_id": "JHS9101"})
    assert t["remaining_hours"] == 133.0                                     # 153 - 20 logged on T3


def test_missing_streak_counts_unsubmitted_working_days(mdb, nq_db):
    now = datetime.utcnow()
    mdb["c_submissions"].insert_one({"employee_id": "JHS9101", "date": "2026-10-12", "submitted_at": now})
    mdb["c_submissions"].insert_one({"employee_id": "JHS9102", "date": "2026-10-14", "submitted_at": now})
    job.run(DAY)
    streak = {t["employee_id"]: t["missing_streak"] for t in mdb["m_team"].find({})}
    assert streak["JHS9101"] == 2                    # 14th and 13th missing, 12th submitted (weekend 10-10/11 irrelevant)
    assert streak["JHS9102"] == 0
    assert streak.get("JHS9104") is None             # not a pilot employee: no compliance figure


def test_streak_skips_hrms_leave_and_holidays(mdb, nq_db):
    mdb["c_submissions"].insert_one({"employee_id": "JHS9101", "date": "2026-10-09", "submitted_at": datetime.utcnow()})
    mdb["c_hrms"].insert_one({"employee_id": "JHS9101", "date": "2026-10-13", "leave_flag": True, "net_hours": None})
    job.run(DAY)
    # 14th, 12th missing; 13th is leave; weekend skipped; 9th submitted
    assert mdb["m_team"].find_one({"employee_id": "JHS9101"})["missing_streak"] == 2


# ── compliance per manager ───────────────────────────────────────────────────

def test_dashboard_daily_counts(mdb):
    now = datetime.utcnow()
    mdb["c_submissions"].insert_one({"employee_id": "JHS9101", "date": "2026-10-14", "submitted_at": now})
    mdb["c_hrms"].insert_one({"employee_id": "JHS9102", "date": "2026-10-14", "leave_flag": True})
    mdb["c_entries"].insert_many([entry("JHS9101", "2026-10-14", 8), entry("JHS9101", "2026-10-14", 1, is_unplanned=True),
                                  entry("JHS9103", "2026-10-14", 8)])
    mdb["c_reco"].insert_many([{"employee_id": "JHS9101", "date": "2026-10-14", "result": "matched"},
                               {"employee_id": "JHS9102", "date": "2026-10-14", "result": "leave"},
                               {"employee_id": "JHS9103", "date": "2026-10-14", "result": "short"}])
    rows = {r["manager_id"]: r for r in agg.compute_dashboard_daily(date(2026, 10, 14))}
    a, b = rows["JHS9001"], rows["JHS9002"]
    assert (a["team_size"], a["expected"], a["submitted"], a["hours"], a["entries"], a["unplanned"]) == (2, 1, 1, 9.0, 2, 1)
    assert a["reco"]["matched"] == 1 and a["reco"]["leave"] == 1
    assert (b["expected"], b["submitted"], b["reco"]["short"]) == (1, 0, 1)
    assert agg.compute_dashboard_daily(date(2026, 10, 17)) == []             # Saturday
    assert agg.compute_dashboard_daily(date(2026, 10, 2)) == []              # holiday in config


# ── job orchestration ────────────────────────────────────────────────────────

def test_first_run_backfills_90_days_then_only_recent_days(mdb, nq_db):
    assert job.default_backfill() == 90
    job.run(DAY, backfill_days=job.default_backfill())
    dates = sorted({r["date"] for r in mdb["m_daily"].find({})})
    assert dates[0] >= "2026-07-17" and dates[-1] == "2026-10-14" and len(dates) > 50
    assert job.default_backfill() == 0
    before = mdb["m_daily"].count_documents({})
    job.run(DAY)                                                             # same day again: nothing duplicated
    assert mdb["m_daily"].count_documents({}) == before


def test_nq_outage_fails_the_job_but_keeps_the_non_nq_parts(mdb, nq_down):
    mdb["c_entries"].insert_one(entry("JHS9101", "2026-10-12", 5))
    with pytest.raises(NQUnavailable):
        job.run(DAY)
    assert mdb["m_hours"].count_documents({}) == 1 and mdb["m_projects"].count_documents({}) == 0


# ── scheduler hook ───────────────────────────────────────────────────────────

def at(h, m=0):
    return scheduler.IST.localize(datetime.fromisoformat(f"2026-10-15T{h:02d}:{m:02d}:00"))


def test_metrics_run_once_after_02_00_ist(mdb):
    calls = []
    fn = lambda d: (calls.append(d) or {"projects": 0})
    assert scheduler.run_metrics_if_due(at(1, 59), fn) is None and not calls
    assert scheduler.run_metrics_if_due(at(2, 0), fn) == {"projects": 0}
    assert scheduler.run_metrics_if_due(at(2, 1), fn) is None and scheduler.run_metrics_if_due(at(23, 0), fn) is None
    assert len(calls) == 1 and mdb["c_job_runs"].find_one({"job": "metrics"})["status"] == "done"


def test_failed_metrics_run_is_retried_but_not_every_tick(mdb):
    def boom(d):
        raise RuntimeError("nq down")
    assert scheduler.run_metrics_if_due(at(2, 0), boom) is None
    assert mdb["c_job_runs"].find_one({"job": "metrics"})["status"] == "failed"
    ok = []
    assert scheduler.run_metrics_if_due(at(2, 1), lambda d: (ok.append(1) or {})) is None and not ok      # too soon
    mdb["c_job_runs"].update_one({"job": "metrics"}, {"$set": {"last_attempt_at": datetime.utcnow() - timedelta(minutes=11)}})
    assert scheduler.run_metrics_if_due(at(2, 12), lambda d: (ok.append(1) or {"x": 1})) == {"x": 1}
    assert ok == [1] and mdb["c_job_runs"].find_one({"job": "metrics"})["status"] == "done"
