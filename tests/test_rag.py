from datetime import date

import pytest

from backend.timesheet.rag import ProjectStats, forecast_end_date, gap_points, rag_status

PLANNED = date(2026, 10, 31)


def stats(**kw):
    base = dict(budget_hours=100, hours_used=0, tasks_total=10, tasks_done=0, overdue_tasks=0,
                days_since_last_entry=1, planned_end=PLANNED, forecast_end=None)
    base.update(kw)
    return ProjectStats(**base)


def test_green_when_everything_is_on_track():
    assert rag_status(stats(hours_used=30, tasks_done=3)) == "green"


@pytest.mark.parametrize("used,done,expected", [
    (10 + 10, 1, "green"),        # gap exactly 10 -> not over 10
    (20.5, 1, "amber"),           # gap 10.5
    (35, 1, "amber"),             # gap exactly 25 -> amber, not red ("more than 25")
    (35.5, 1, "red"),             # gap 25.5
])
def test_gap_thresholds(used, done, expected):
    s = stats(hours_used=used, tasks_done=done)
    assert gap_points(s) == pytest.approx(used - done * 10)
    assert rag_status(s) == expected


def test_any_overdue_task_is_red():
    assert rag_status(stats(overdue_tasks=1)) == "red"


@pytest.mark.parametrize("days,expected", [(0, "green"), (1, "amber"), (7, "amber"), (8, "red")])
def test_forecast_lateness(days, expected):
    fe = date.fromordinal(PLANNED.toordinal() + days)
    assert rag_status(stats(forecast_end=fe)) == expected


def test_early_forecast_is_green():
    assert rag_status(stats(forecast_end=date(2026, 10, 20))) == "green"


@pytest.mark.parametrize("idle,expected", [(13, "green"), (14, "amber"), (30, "amber"), (None, "green")])
def test_idle_days(idle, expected):
    assert rag_status(stats(days_since_last_entry=idle)) == expected


def test_thresholds_come_from_config():
    s = stats(hours_used=35.5, tasks_done=1)                       # gap 25.5 -> red by default
    assert rag_status(s) == "red"
    assert rag_status(s, {"red_gap_pts": 40}) == "amber"           # config relaxes it
    assert rag_status(stats(days_since_last_entry=5), {"amber_idle_days": 5}) == "amber"


def test_zero_budget_and_zero_tasks_do_not_divide_by_zero():
    assert gap_points(stats(budget_hours=0, tasks_total=0)) == 0
    assert rag_status(stats(budget_hours=0, tasks_total=0)) == "green"


def test_forecast_end_from_burn():
    # started Mon 2026-10-05, today Fri 2026-10-09 (5 working days), 25h used -> 5h/day;
    # budget 100h, 25% of tasks done -> 75h left -> 15 working days after 10-09 -> Fri 2026-10-30
    assert forecast_end_date(date(2026, 10, 9), date(2026, 10, 5), 25, 100, 25) == date(2026, 10, 30)
    # a holiday on 2026-10-12 pushes it one working day later
    assert forecast_end_date(date(2026, 10, 9), date(2026, 10, 5), 25, 100, 25, [date(2026, 10, 12)]) == date(2026, 11, 2)
    assert forecast_end_date(date(2026, 10, 9), date(2026, 10, 5), 0, 100, 25) is None      # no burn yet
    assert forecast_end_date(date(2026, 10, 9), None, 25, 100, 25) is None
    assert forecast_end_date(date(2026, 10, 9), date(2026, 10, 5), 25, 100, 100) == date(2026, 10, 9)   # all done
