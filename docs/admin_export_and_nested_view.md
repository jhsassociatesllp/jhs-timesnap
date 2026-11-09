# Admin data export and the nested view

## Data export page (admins only)
Menu: **Data export** (`/static/timesheet/export.html`). Choose From / To, optionally employee codes (comma separated), and
Excel or CSV, then press Download on a dataset:

| Dataset | Contents |
|---|---|
| Timesheet entries (My day) | every work row with employee, manager, payroll, cycle, task, hours, remarks, approved/locked |
| Cycle summary per employee | per employee per 10-day cycle: days, entries, hours, unplanned rows, approval status |
| Submitted days / Saved days | day_submissions / day_drafts |
| Manager approvals and send-backs | cycle_reviews: status, who, note, classic-copy result |
| HRMS attendance, Hours reconciliation | hrms_attendance, daily_reco |
| Classic timesheet | Timesheet_data rows (including approved My day cycles copied there) |
| Export log | who exported what (last 5,000) |

Limits: ranges up to 366 days, 200,000 rows per file, cells starting with `= + - @` are neutralised, every export is logged
in `export_audit`. API: `GET /admin-exports/datasets`, `GET /admin-exports/{dataset}?from=&to=&employee=&format=`.

## Nested view `employee_timesheets` (read-only, in Compass)
employee > payrolls (21st-20th, `payroll_id` = month it ends in, `2026-10` = 21 Sep - 20 Oct 2026) > 3 cycles > entries.
A saved aggregation over `timesheet_entries`; nothing is copied and the app never reads it (no extra load). Create once:

```
python -m backend.timesheet.nested_view status
python -m backend.timesheet.nested_view create --yes
```
It prints which database it will change and needs `--yes`. `drop --yes` removes only the view.
Corrections are made on `timesheet_entries` (one row per entry), not in the view.
