# Step 3 – "My day" timesheet (pilot employees only)

`/timesheet` now opens the day-by-day "My day" screen for **pilot employees**. Everyone else is sent to the
classic grid (`/static/timesheet/index.html`), unchanged. Pilot employees can still open the classic grid from
the "Classic view" link.

## What it does
- Pick a task (searchable, grouped by client › project); client, project and code fill in from Nexus Quant.
- Type hours per row, optional "What I did", Status (Done / In progress / Blocked).
- Location per day: Office, Client site, WFH, Leave, Week off, PHY (Leave / Week off / PHY need no rows).
- "Unplanned work" row: the description is required (it is the reason); the manager reviews it.
- Autosave ("Saved ✓"), "Submit day", day strip for the 10-day cycle (submitted / saved / missing / off).
- Cycle deadline = cycle end + 5 days, 23:59 IST. After that, days are view only.
- No HRMS data is shown or used here; the reconciliation compares typed hours later.

## Set up a pilot (local)
```
python -m backend.timesheet.pilot add JHS####      # yourself, and your manager
python -m backend.timesheet.pilot list
```
Restart the app, hard-refresh (Ctrl+F5). Start the pilot at the start of a cycle (1st / 11th / 21st).
Old submitted days of pilot employees can be copied with `migrate_timesheet_entries.py` (dry run first, on a COPY).

## Data source
- Fake NQ: `docker compose -f docker-compose.dev.yml up -d`, `.env.example` values, employee `JHS9101`.
- Real NQ (read-only, through the tunnel) with your own employee id.

## Not in this step
Manager approval per cycle and the mirror into the old reports (Step 4); Excel template / grid export (Step 2b).
