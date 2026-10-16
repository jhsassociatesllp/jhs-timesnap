from datetime import date

import pytest

from backend.timesheet import rules as r


def test_net_hours_subtracts_lunch_and_never_negative():
    assert r.net_hours(9.0) == 8.5
    assert r.net_hours(0.25) == 0.0


def test_working_days_skips_weekends_and_holidays():
    # Mon 2026-10-05 .. Sun 2026-10-11 -> 5 working days
    assert r.working_days(date(2026, 10, 5), date(2026, 10, 11)) == 5
    # a holiday on Wed 10-07 removes one; a holiday on a Saturday changes nothing
    assert r.working_days(date(2026, 10, 5), date(2026, 10, 11), [date(2026, 10, 7)]) == 4
    assert r.working_days(date(2026, 10, 5), date(2026, 10, 11), [date(2026, 10, 10)]) == 5
    assert r.working_days(date(2026, 10, 5), date(2026, 10, 5)) == 1       # single day
    assert r.working_days(date(2026, 10, 10), date(2026, 10, 11)) == 0     # weekend only
    assert r.working_days(date(2026, 10, 9), date(2026, 10, 5)) == 0       # end before start


def test_budget_hours_weekends_holidays_allocation():
    s, e = date(2026, 10, 5), date(2026, 10, 11)
    assert r.budget_hours(s, e) == 42.5                      # 5 x 8.5
    assert r.budget_hours(s, e, [date(2026, 10, 7)]) == 34.0  # holiday
    assert r.budget_hours(s, e, allocation_pct=50) == 21.25
    assert r.budget_hours(None, e) == 0.0


def test_tolerance_boundary():
    assert r.within_tolerance(8.0, 8.5)        # diff -0.5 -> matched
    assert r.within_tolerance(9.0, 8.5)        # diff +0.5 -> matched
    assert not r.within_tolerance(7.75, 8.5)   # short by 0.75
    assert not r.within_tolerance(9.25, 8.5)   # over by 0.75
    assert r.difference(7.5, 8.5) == -1.0


def test_one_task_autofill_and_awaiting():
    assert r.one_task_hours(1, 8.0) == (8.0, True, False)
    assert r.one_task_hours(1, None) == (None, True, True)       # awaiting HRMS
    assert r.one_task_hours(2, 8.0) == (None, False, False)      # employee enters hours
    assert r.one_task_hours(0, 8.0) == (None, False, False)


@pytest.mark.parametrize("h,ok", [(0.25, True), (1, True), (7.75, True), (24, True),
                                  (0, False), (-1, False), (0.3, False), (24.25, False),
                                  ("x", False), (None, False)])
def test_valid_hours(h, ok):
    assert r.valid_hours(h) is ok


@pytest.mark.parametrize("d,cid,start,end,deadline", [
    (date(2026, 10, 1),  "2026-10-C1", date(2026, 10, 1),  date(2026, 10, 10), date(2026, 10, 15)),
    (date(2026, 10, 10), "2026-10-C1", date(2026, 10, 1),  date(2026, 10, 10), date(2026, 10, 15)),
    (date(2026, 10, 11), "2026-10-C2", date(2026, 10, 11), date(2026, 10, 20), date(2026, 10, 25)),
    (date(2026, 10, 20), "2026-10-C2", date(2026, 10, 11), date(2026, 10, 20), date(2026, 10, 25)),
    (date(2026, 10, 21), "2026-10-C3", date(2026, 10, 21), date(2026, 10, 31), date(2026, 11, 5)),
    (date(2026, 2, 28),  "2026-02-C3", date(2026, 2, 21),  date(2026, 2, 28),  date(2026, 3, 5)),
    (date(2028, 2, 29),  "2028-02-C3", date(2028, 2, 21),  date(2028, 2, 29),  date(2028, 3, 5)),   # leap year
    (date(2026, 4, 30),  "2026-04-C3", date(2026, 4, 21),  date(2026, 4, 30),  date(2026, 5, 5)),   # 30-day month
    (date(2026, 12, 31), "2026-12-C3", date(2026, 12, 21), date(2026, 12, 31), date(2027, 1, 5)),   # year rollover
])
def test_cycle_for(d, cid, start, end, deadline):
    c = r.cycle_for(d)
    assert (c.id, c.start, c.end, c.deadline) == (cid, start, end, deadline)
