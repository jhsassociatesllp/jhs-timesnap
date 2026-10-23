# Admin setup, Review team and the submitted-day lock

## Admin setup (`/static/timesheet/admin.html`, admins only; menu: Admin setup)
1. **Payrolls and cycles.** "Create payroll" asks for the month the payroll ENDS in (2026-10 = 21 Sep - 20 Oct 2026). The three sub-cycles
   (21-end of the previous month, 1-10, 11-20) appear with a live preview and a deadline each (cycle end + N days, 23:59 IST; N is editable
   per payroll, and each deadline can be changed afterwards). A payroll with timesheet data cannot be deleted.
   **Only cycles that belong to a created payroll can be filled in (My day) or reviewed (Review team).**
2. **Working rules.** Hours in a working day (8.5), week-off days (Sat and Sun ticked), holidays (date and name), default deadline days.
   They drive the allotted hours on Review and the working days in the day strip.
3. **Who uses My day.** All employees, or only a list of codes (staged roll-out), plus "always include" codes for free-text staff.
4. **Allow changes to a day.** Find an employee's submitted days and press Allow (a reason is required). They can change that day once and
   submit it again; it locks again after they submit. Not possible for classic days or for a cycle the manager has approved (unlock the cycle first).
Every change is written to `cycle_reviews` (`admin_change`, `day_reopen`). API: `/timesheet/v2/admin/*`.

## My day: a submitted day is locked
After "Submit day" the day is read-only. It opens again only when an admin allows it, or when the manager sends the cycle back.

## Review team (team leads and admins)
- The cycle list shows only created payrolls and their three sub-cycles.
- **Review** opens a modal: per date and task the hours that day, the total hours on the task, the hours ALLOTTED to the task
  (working days between its Nexus Quant start and end date x hours per day, minus week-off days and holidays) and a result:
  completed within / over the allotted hours, in progress within / over, unplanned. A summary line counts them.
- One remarks box: optional when approving, required when sending back. Approving is allowed at any time (before the cycle ends it asks
  for a confirmation because it locks the days not yet filled).

Removed for now (to be rebuilt step by step): Team dashboard, Reconciliation, Late projects.


## HRMS attendance and the typed-hours comparison
- **Upload** (menu: HRMS upload, admins): the HRMS "Attendance" export (.xlsx or .csv) with one row per employee per day. The column titles may
  sit below a title line. Read: Employee Code, Date, Muster, In Time, Out Time. One document per employee per date is stored in
  `hrms_attendance` (status, in, out, gross hours = out - in; the "Total Hours" column is hours.minutes and is never used). Re-uploading is safe.
  An out punch after midnight (before 06:00) counts as the next morning; a present day with out before in, or more than 18 hours, is
  reported as a row error and skipped. Rows with no status and no punches are ignored. Muster PST = present, ABS = absent, WEO = weekly off,
  PHY / HOL = holiday, CL / SL / PL = leave. Dates where almost everyone is on holiday are added to the holiday list automatically.
- **Review team**, per employee: the team table shows Typed hrs, HRMS hrs and Difference; the modal shows, per date, the HRMS status, in and
  out times, HRMS hours (gross minus lunch), typed hours, the difference and a result (matched, typed less, typed more, hours typed with no
  punch, punched with nothing typed, off/leave). Lunch (0.5 h) and the matching tolerance (0.5 h) are set in Admin setup, Working rules.
- The task table in the modal has **Client** and **Project** columns right after the date.
- Nothing is precomputed: the comparison is calculated when a team lead opens the screen.
