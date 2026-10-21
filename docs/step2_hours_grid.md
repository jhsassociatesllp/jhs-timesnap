# Step 2 - simpler row: employees type their own hours

HRMS is NOT used while filling the timesheet (there is no HRMS connection). Employees always type their hours;
hours are compared with HRMS later, date by date, in a separate reconciliation (weekly / every 10 days / monthly).

## The row now
`Date | Location | Client | Project | Project Code | Reporting Manager | Activity | Project Hours | Remarks`

Removed from the entry grid, the edit modal and the summary boxes: Project Start, Project End, Lunch Time,
Travel Time, Billable (and the Billable / Non-billable summary boxes).

- **Location** dropdown: Office, Client site, WFH, Leave, Week off, PHY. The stored values are unchanged
  (`Client Site`, `Work From Home`, `Week Off`), so saved entries, reports and server rules keep working. "Field
  Work" is no longer offered; older rows that have it still display it.
- **Project Hours** is a number box (0.25 steps suggested). A day off (Leave / Week off / PHY) clears and disables it.
  If a date's rows add up to more than 24 hours the boxes turn red.

## What the server enforces at submit
- Working-day rows: hours more than 0 and at most 24 (up to 2 decimals); a date's rows together at most 24.
- Day-off rows carry no hours (any typed hours are cleared).
- Start/end time, lunch and travel are no longer required. Older drafts that still carry them keep their values.
- Everything from Step 1 (assigned NQ activity or Other + reason) is unchanged.

## Excel upload (works with both layouts)
Accepts files without the removed columns (hours typed in `Project Hours`) AND files made from the old template
(hours then come from Project Start/End when `Project Hours` is empty). Hours missing/invalid -> the upload is
refused with the row and date.

## Not in this step
- **Step 2b:** the Excel **template download** and the grid **export** still contain the old columns; they will be
  rebuilt with the new layout (column letters in the template are hard-coded, so it gets its own check).
- History, approval and manager tables are unchanged: old rows show their old values, new rows show blanks for the
  removed columns. They are tidied in Step 4 (approvals).
- Billable split: new entries have no billable value, so "billable / non-billable" totals show 0 for them; total
  hours stay correct.
- HRMS reconciliation (date-wise, entered hours vs HRMS) comes after the sub-cycle and approval steps.
