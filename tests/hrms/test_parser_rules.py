import csv
import io
from datetime import time

import pytest

from backend.hrms import rules
from backend.hrms.parser import HrmsFileError, parse_hrms, parse_time
from tests.hrms import sample


# ── rules ────────────────────────────────────────────────────────────────────

def test_gross_and_net_from_punches_ignoring_total_hours_column():
    assert rules.gross_hours(time(9, 58, 48), time(19, 44, 4)) == 9.75     # NOT 9.46 (hours.minutes)
    assert rules.net_from_gross(9.75) == 9.25
    assert rules.gross_hours(None, time(18, 0)) is None
    with pytest.raises(ValueError):
        rules.gross_hours(time(18, 0), time(9, 0))


def test_classify_codes_and_unknown():
    for code, kind in [("PST", "working"), ("hd", "working"), ("WEO", "weekly_off"), ("HOL", "holiday"),
                       ("CL", "leave"), ("SL", "leave"), ("PL", "leave"), ("ABS", "absent")]:
        assert rules.classify(code) == kind
    assert rules.classify("XYZ") == "unknown" and rules.classify("") == "unknown"
    assert rules.classify("XYZ", {"XYZ": "leave"}) == "leave"              # config override


@pytest.mark.parametrize("kind,n,hours,net,expected", [
    ("leave", 0, 0, None, "leave"), ("holiday", 2, 8, None, "leave"), ("weekly_off", 0, 0, None, "leave"),
    ("working", 0, 0, 8.5, "not_filled"),
    ("working", 2, 8.0, 8.5, "matched"),          # diff -0.5 boundary
    ("working", 2, 9.0, 8.5, "matched"),          # diff +0.5 boundary
    ("working", 2, 7.75, 8.5, "short"),
    ("working", 2, 9.25, 8.5, "over"),
    ("working", 2, 8.0, None, "no_punch"),
    ("working", 0, 0, None, None),                # present, no punch, nothing filled -> nothing to flag
    ("absent", 1, 4, None, "no_punch"), ("absent", 0, 0, None, None),
    ("unknown", 1, 8, 8.0, None),
])
def test_reco_result(kind, n, hours, net, expected):
    assert rules.reco_result(kind, n, hours, net) == expected


# ── parser ───────────────────────────────────────────────────────────────────

def test_parse_sample_workbook():
    res = parse_hrms(sample.build_bytes(), "hrms.xlsx")
    assert res.total_rows == 15 and len(res.rows) == 15 and not res.errors and not res.warnings
    assert (res.date_from, res.date_to) == ("2026-10-02", "2026-10-14")
    by = {(r["employee_id"], r["date"]): r for r in res.rows}
    r = by[("JHS9101", "2026-10-13")]
    assert (r["in_time"], r["out_time"], r["gross_hours"], r["net_hours"], r["kind"]) == \
           ("09:58", "19:44", 9.75, 9.25, "working")
    assert by[("JHS9102", "2026-10-13")]["leave_flag"] is True              # CL
    assert by[("JHS9102", "2026-10-14")]["net_hours"] is None               # present, no punch
    assert by[("JHS9103", "2026-10-13")]["kind"] == "absent"
    assert by[("JHS9103", "2026-10-14")]["net_hours"] == 3.5                # half day
    assert by[("JHS9101", "2026-10-02")]["kind"] == "holiday"
    assert set(r.keys()) >= {"employee_id", "date", "in_time", "out_time", "gross_hours", "net_hours", "status_code"}
    assert "employee_name" not in r                                         # personal data not carried over


def test_parse_native_excel_types():
    import datetime as dt
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Employee Code", "Date", "In Time", "Out Time", "Muster"])
    ws.append(["JHS9101", dt.datetime(2026, 10, 12), dt.time(9, 30), dt.time(18, 30), "PST"])
    ws.append(["JHS9101", dt.datetime(2026, 10, 13), 0.4375, 0.75, "PST"])    # Excel fractions: 10:30 - 18:00
    buf = io.BytesIO(); wb.save(buf)
    res = parse_hrms(buf.getvalue(), "x.xlsx")
    assert not res.errors and res.rows[0]["net_hours"] == 8.5
    assert (res.rows[1]["in_time"], res.rows[1]["out_time"], res.rows[1]["net_hours"]) == ("10:30", "18:00", 7.0)


def test_row_errors_are_reported_not_fatal():
    rows = list(sample.ROWS[:1]) + [
        ("", "12/10/2026", "PST", "09:00:00 AM", "06:00:00 PM", ""),          # no employee
        ("JHS9101", "31/02/2026", "PST", "", "", ""),                           # bad date
        ("JHS9101", "12/10/2026", "PST", "06:00:00 PM", "09:00:00 AM", ""),   # out before in
        ("JHS9101", "12/10/2026", "PST", "09:00:00 AM", "06:00:00 PM", ""),   # good
        ("JHS9101", "12/10/2026", "PST", "09:00:00 AM", "06:00:00 PM", ""),   # duplicate
        ("JHS9101", "12/10/2026", "ZZZ", "", "", ""),                          # (dup too)
        ("JHS9102", "12/10/2026", "ZZZ", "", "", ""),                          # unknown code -> warning
    ]
    res = parse_hrms(sample.build_bytes(rows), "x.xlsx")
    assert len(res.rows) == 3                                                   # holiday row + good + unknown-code row
    assert sorted(e["row"] for e in res.errors) == [3, 4, 5, 7, 8]
    assert any("duplicate" in e["message"] for e in res.errors)
    assert res.unknown_codes == {"ZZZ": 1} and res.warnings


def test_missing_required_column_and_bad_files():
    headers = [h for h in sample.HEADERS if h != "Out Time"]
    with pytest.raises(HrmsFileError, match="Out Time"):
        parse_hrms(sample.build_bytes([], headers), "x.xlsx")
    with pytest.raises(HrmsFileError):
        parse_hrms(b"hello", "x.txt")
    with pytest.raises(HrmsFileError):
        parse_hrms(b"not really excel", "x.xlsx")
    with pytest.raises(HrmsFileError):
        parse_hrms(b"x" * (10 * 1024 * 1024 + 1), "x.xlsx")


def test_csv_and_tab_separated():
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Employee Code", "Date", "In Time", "Out Time", "Muster"])
    w.writerow(["JHS9101", "12/10/2026", "09:30:00 AM", "06:30:00 PM", "PST"])
    res = parse_hrms(buf.getvalue().encode(), "x.csv")
    assert res.rows[0]["net_hours"] == 8.5
    tsv = "Employee Code\tDate\tIn Time\tOut Time\tMuster\nJHS9101\t12/10/2026\t09:30 AM\t06:30 PM\tPST\n"
    assert parse_hrms(tsv.encode(), "x.csv").rows[0]["gross_hours"] == 9.0


def test_parse_time_variants():
    assert parse_time("09:58:48 AM") == time(9, 58, 48)
    assert parse_time("6:30 pm") == time(18, 30)
    assert parse_time("") is None and parse_time(None) is None
    with pytest.raises(ValueError):
        parse_time("nonsense")
