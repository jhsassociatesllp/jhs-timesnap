# Step 4 – Manager review, locks and the mirror to the classic reports

## Manager screen: `/static/timesheet/review.html`
("Review" link in the My day header, shown only to managers and admins.)
- Pick a 10-day cycle. The table lists your pilot reportees: days filled, hours, unplanned rows, status, open items.
- Click a name to see each day's rows (unplanned work is highlighted).
- **Approve & lock** (one or many). Only after the cycle has ended. If someone has missing days or open hours gaps
  you must tick the confirmation and press Approve again.
- **Send back with note**: the cycle reopens for that employee, even after the deadline, until you approve it.
  The employee sees the note on My day. When they submit days again the row shows "Resubmitted".
- Admin only: **Unlock** an approved cycle (reason required, audited).

## What approve does
1. Entries become approved + locked; My day refuses every change in that cycle.
2. The cycle is copied into the classic `Timesheet_data` (rows flagged `v2_mirror`), merged into the matching
   21st-to-20th payroll. Other rows of that payroll are never touched.
3. The classic payroll becomes "approved" (and moves to the classic Approved list) only when all three
   10-day cycles inside it are approved.
4. If the copy fails the approval still stands; the row shows "Copy to classic reports failed" and an admin can re-run
   `POST /timesheet/v2/cycles/{cycle}/mirror`.

## Guards
- Dashboards ignore mirrored rows (no double counting).
- The classic "submit" refuses to run for a payroll that already holds mirrored rows (it would overwrite them).
- Role checks on every endpoint: reporting manager (own reportees), admin; employees get 403.

## Not in this step
Email to the employee on send-back (note is shown on My day only); restyle of the other dashboards.
