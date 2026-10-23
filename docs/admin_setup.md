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
