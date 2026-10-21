# Step 2b – Excel template, export and upload (classic grid)

Columns (template and export are identical, so an export can be edited and uploaded again):
`Employee ID, Employee Name, Designation, Gender, Partner, Reporting Manager, Date, Work, Client, Project, Project Code,
Reporting Manager Entry, Activity, Project Hours, Remarks, 3 Hits, 3 Misses, Feedback for HR, Feedback for IT,
Feedback for CRM, Feedback for Others`.

Removed: Project Start Time, Project End Time, Billable, Lunch Time, Travel Time (history export also drops the billable totals).

Template
- Work: Office, Client Site, Work From Home, Leave, Week Off, PHY.
- Project Hours is typed (0.25 to 24); no formula any more.
- Activity: dropdown of the employee's own open Nexus Quant tasks, plus "Other". A new "My tasks" tab lists each task with its project and dates.
- Client > Project > Project Code work as before. Free-text employees (partner JHS01, JHS1562) keep free-typed Activity.

Upload
- Both the old and the new layout are accepted.
- Activity is matched (case-insensitive) to the employee's task of that project code and the row gets its task id.
- "Other" needs the reason in Remarks. Text that is not one of the employee's tasks is rejected with the row number.
