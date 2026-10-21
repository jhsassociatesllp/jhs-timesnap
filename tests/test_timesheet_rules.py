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


def test_cycle_from_id_round_trip_and_rejects_garbage():
    for d in (date(2026, 10, 1), date(2026, 10, 15), date(2026, 2, 28), date(2028, 2, 29), date(2026, 12, 31)):
        assert r.cycle_from_id(r.cycle_for(d).id) == r.cycle_for(d)
    for bad in ("", "2026-10", "2026-13-C1", "2026-10-C4", "x-y-C1", "2026-10-C1; drop", None):
        with pytest.raises(ValueError):
            r.cycle_from_id(bad)


# ── hours typed by the employee (no start/end time any more) ────────────────────────────────────

OFF = {"Leave", "PHY", "Week Off"}


def _row(hours, date="2026-10-14", location="Office"):
    return {"projectHours": hours, "date": date, "location": location}


def test_project_hours_errors_accepts_normal_days():
    assert r.project_hours_errors([_row("8"), _row("7.5", "2026-10-15"), _row("0.25", "2026-10-16")], OFF) == []
    assert r.project_hours_errors([_row("4"), _row("4.5")], OFF) == []                 # two rows, same day, 8.5 total
    assert r.project_hours_errors([_row("12"), _row("12")], OFF) == []                 # exactly 24 in a day is allowed
    assert r.project_hours_errors([_row(8.33)], OFF) == []                             # older computed hours (2 decimals)


@pytest.mark.parametrize("bad", ["", None, "abc", "0", "0.0", "-1", "24.01", "25", "8,5", "8.333", " "])
def test_project_hours_errors_rejects_bad_values(bad):
    errs = r.project_hours_errors([_row("8"), _row(bad, "2026-10-15")], OFF)
    assert len(errs) == 1 and errs[0].startswith("Row 2: enter project hours")


def test_project_hours_errors_day_total_and_day_off_rows():
    errs = r.project_hours_errors([_row("12"), _row("12.5")], OFF)
    assert errs == ["2026-10-14: total hours 24.5 are more than 24 for one day"]
    # a day off needs no hours, and hours typed on it are ignored (not counted towards anything)
    assert r.project_hours_errors([_row("", location="Leave"), _row(None, location="Week Off"),
                                   _row("30", location="PHY")], OFF) == []
    # row numbers are 1-based positions, like the other submit checks
    assert r.project_hours_errors([_row("8"), _row("8", location="Leave"), _row("")], OFF)[0].startswith("Row 3:")


# ── day-by-day timesheet rules ───────────────────────────────────────────────────────────────────────

from datetime import datetime  # noqa: E402


@pytest.mark.parametrize("h,ok", [(0.25, True), (8, True), ("7.5", True), (24, True), (8.33, True),
                                  (0, False), (-1, False), (24.01, False), (8.333, False), ("x", False), (None, False), ("", False)])
def test_typed_hours_ok(h, ok):
    assert r.typed_hours_ok(h) is ok


def test_deadline_is_end_plus_five_days_at_23_59_ist():
    c = r.cycle_for(date(2026, 10, 14))                                  # 11-20 Oct -> deadline 25 Oct
    assert not r.deadline_passed(c, datetime(2026, 10, 25, 23, 59, 59))
    assert r.deadline_passed(c, datetime(2026, 10, 26, 0, 0, 0))
    assert not r.deadline_passed(c, datetime(2026, 10, 14, 12, 0))


def _e(hours, unplanned=False, remarks=""):
    return {"hours": hours, "is_unplanned": unplanned, "remarks": remarks}


def test_day_submit_errors():
    assert r.day_submit_errors("Office", [_e(4), _e(4.5)]) == []
    assert r.day_submit_errors("Leave", []) == [] and r.day_submit_errors("Week Off", []) == [] and r.day_submit_errors("PHY", []) == []
    assert "day off carries no work rows" in r.day_submit_errors("Leave", [_e(8)])[0]
    assert r.day_submit_errors("Office", []) == ["Add at least one task for the day"]
    assert r.day_submit_errors("WFH?", [])[0].startswith("Add at least one")        # unknown location is just a working day
    errs = r.day_submit_errors("Office", [_e(None), _e(0), _e(25)])
    assert [x.split(":")[0] for x in errs] == ["Row 1", "Row 2", "Row 3"]
    assert "add up to 26" not in " ".join(errs)                                      # invalid rows are not summed
    assert r.day_submit_errors("Office", [_e(12), _e(12.5)]) == ["The day's hours add up to 24.5 - more than 24"]
    assert r.day_submit_errors("Client Site", [_e(12), _e(12)]) == []                # exactly 24 is allowed
    assert r.day_submit_errors("Office", [_e(2, True, "ab")]) == ["Row 1: describe the unplanned work"]
    assert r.day_submit_errors("Office", [_e(2, True, "Ad-hoc data pull")]) == []
