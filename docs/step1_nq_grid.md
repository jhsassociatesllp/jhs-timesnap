# Step 1 - the existing timesheet grid reads clients, projects and activities from Nexus Quant

Scope: ONLY the data source and the Activity column of the existing grid (`/timesheet`). Times, hours, billable,
lunch, remarks, drafts, submit, history, manager approval and reports are unchanged.

## What the employee sees
- **Client -> Project -> Project code** lists contain only what is **assigned to them in Nexus Quant** (active
  projects). The project code still auto-fills.
- **Activity** is a dropdown of their NQ tasks for the chosen client + project + the row's date:
  the task window overlaps the date, or the task ended before it and is still open (overdue). Finished tasks are
  offered only for dates inside their window. Sub-tasks are included.
- **Other (not in my assigned list)** switches the cell to a free-text "What did you do?" plus a required reason
  (the manager sees it). "pick from my assigned list" goes back.
- Client **Other** (existing behaviour) and the free-text employees (partner `JHS01`, `JHS1562`) keep plain text boxes.
- Changing client / project clears the activity; changing the date keeps it only if it still applies.
- Banner above the cycle selector when NQ is unreachable ("project data unavailable"), possibly stale, or when nothing
  is assigned yet. Already-saved rows are never touched.

## What the server enforces
- `GET /timesheet/projects/{id}` (also `/get_employee_projects/{id}`): same JSON keys as before
  (`clients`, `projects_by_client`, `partner_emp_code`) + `activities_by_project`, `source`, `nq_unavailable`,
  `nq_data_may_be_stale`. The old Mongo `Projects` collection is no longer used for this list.
- **Submit**: every working-day row needs a valid assigned `nqTaskId` that belongs to the row's project code, or
  `activityOther` with a reason. Day-off rows, client "Other" rows and free-text employees are exempt. NQ unreachable
  at submit time -> 503 "try again" (nothing is guessed).
- **History edit** (`PUT /update_timesheet/...`) cannot bypass the rule when the activity is changed.
- The TL "project plan" check now means "the project has tasks in Nexus Quant" (falls back to the old Mongo lookup
  if NQ is down).
- Entries keep the same `Timesheet_data` structure; three optional fields are added: `nqTaskId`, `activityOther`,
  `activityReason`. Existing reports and exports keep working.

## Switch / rollback
- `config` document `{_id: "timesheet"}`: `nq_activity_required` (default **true**). Set `false` to turn the submit
  rule off while keeping the NQ lists.
- Old drafts and Excel-uploaded rows have free-text activities with no task id: they are kept as typed, and at submit
  the employee is asked to pick an assigned activity (or Other + reason) for those rows.

## Not in this step (agreed order)
2. Simplify the row (hours from HRMS when one entry that day) - 3. Three 10-day sub-cycles with +5-day deadlines -
4. Manager approval three times per payroll cycle - 5. Manager dashboard of filled timesheets.
