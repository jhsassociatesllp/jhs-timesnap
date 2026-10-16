"""
Builds a DUMMY HRMS export shaped like the real one (same 37 headers, fake people).
  python -m tests.hrms.sample docs/hrms_sample.xlsx
'Total Hours' is deliberately hours.minutes, like the real file (9.46 = 9h46m) - the parser must ignore it.
"""
import io
import sys

import openpyxl

HEADERS = [
    "Employee Code", "Employee Name", "Date of Joining", "Date of Exit", "Manager Code", "Manager Name",
    "Branch Code", "Branch Name", "Department Code", "Department Name", "Designation Code",
    "Designation Name", "Grade Code", "Grade Name", "Project Code", "Project Name", "Division Code",
    "Division Name", "Employee Category Code", "Employee Category Name", "Unit Code", "Unit Name",
    "Date", "Muster", "Roster", "Muster Shift", "Appliction Status", "In Time", "Out Time", "Late Mark",
    "Late Hours", "Early Mark", "Early Hours", "OT Hours", "OT Shift", "Total Hours", "Final Status",
]

# (employee, date dd/mm/yyyy, muster, in, out, Total Hours as hours.minutes)
ROWS = [
    ("JHS9101", "02/10/2026", "HOL", "", "", ""),
    ("JHS9102", "02/10/2026", "HOL", "", "", ""),
    ("JHS9103", "02/10/2026", "HOL", "", "", ""),
    ("JHS9101", "10/10/2026", "WEO", "", "", ""),
    ("JHS9102", "10/10/2026", "WEO", "", "", ""),
    ("JHS9103", "10/10/2026", "WEO", "", "", ""),
    ("JHS9101", "12/10/2026", "PST", "09:30:00 AM", "06:30:00 PM", "9.00"),   # gross 9.00 net 8.50
    ("JHS9101", "13/10/2026", "PST", "09:58:48 AM", "07:44:04 PM", "9.46"),   # gross 9.75 net 9.25
    ("JHS9101", "14/10/2026", "PST", "09:30:00 AM", "06:30:00 PM", "9.00"),   # gross 9.00 net 8.50
    ("JHS9102", "12/10/2026", "PST", "10:00:00 AM", "05:30:00 PM", "7.30"),   # gross 7.50 net 7.00
    ("JHS9102", "13/10/2026", "CL", "", "", ""),                              # leave
    ("JHS9102", "14/10/2026", "PST", "", "", ""),                             # present, no punch
    ("JHS9103", "12/10/2026", "PST", "09:00:00 AM", "06:00:00 PM", "9.00"),
    ("JHS9103", "13/10/2026", "ABS", "", "", ""),                             # absent
    ("JHS9103", "14/10/2026", "HD", "09:30:00 AM", "01:30:00 PM", "4.00"),   # half day gross 4.00 net 3.50
]


def build_workbook(rows=ROWS, headers=HEADERS) -> openpyxl.Workbook:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(headers)
    col = {h: i for i, h in enumerate(headers)}
    for emp, d, muster, t_in, t_out, total in rows:
        r = [""] * len(headers)
        r[col["Employee Code"]] = emp
        r[col["Employee Name"]] = "Dummy Person " + emp[-4:]
        r[col["Manager Code"]] = "JHS9001"
        r[col["Date"]] = d
        r[col["Muster"]] = muster
        r[col["In Time"]] = t_in
        r[col["Out Time"]] = t_out
        r[col["Total Hours"]] = total
        r[col["Final Status"]] = " " + muster
        ws.append(r)
    return wb


def build_bytes(rows=ROWS, headers=HEADERS) -> bytes:
    buf = io.BytesIO()
    build_workbook(rows, headers).save(buf)
    return buf.getvalue()


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "hrms_sample.xlsx"
    build_workbook().save(out)
    print("wrote", out)
