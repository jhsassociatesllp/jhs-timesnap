# Staging merge checklist - `feature/project-tracking`

Branch facts (at review time): 25 commits, 4 existing files modified (`main.py`, `backend/database.py`,
`requirements.txt`, `static/timesheet/index.html`), 80 files added, 224 automated tests passing locally on
Python 3.10. A dry-run merge into `origin/staging` is clean (no textual conflicts; `main.py` was edited on both sides
and merged automatically). The legacy timesheet router, admin module and `.github/` workflow are untouched.

## 0. BLOCKERS - do these BEFORE the first `git push` of this branch

The GitHub repository is **PUBLIC**. Anything pushed is world-readable and permanent in history.

- [ ] **`docs/nq_schema.sql` is the real Nexus Quant database structure** (table names and every column,
      including the credential columns of `tbl_user`). It is in commit `fd810c6`. Do not push it.
      Options: (a) rewrite the unpushed branch history to drop it and commit a **sanitized** schema (only tables /
      columns the app reads; no credential columns) or (b) keep the real dump out of git and generate it per developer.
      A new commit that deletes the file is NOT enough - it would stay in history.
- [ ] **`CLAUDE.md` and `PROMPTS.md` are untracked.** `CLAUDE.md` names internal servers, the tunnel and MySQL user
      roles. Do not commit them to a public repo (add to `.git/info/exclude`), or publish a trimmed copy.
- [ ] Confirm no real secrets are in the diff: `git diff main..HEAD | grep -i -E "password|secret|key"` should only show
      dummy dev values (`dev_ro_pass`, ...) and `${{ secrets.X }}` references. (Reviewed: clean.)
- [ ] The local `.env` holds a pasted private SSH key. Replace it with a key FILE path and rotate that key if it was ever
      shared. `.env` is git-ignored (verified) but keep it that way.

## 1. Before merging into staging

- [ ] Rebase or merge `origin/staging` into the branch (`staging` is 14 commits ahead of `main`: Resume Ranker work).
      Re-run `pytest` afterwards. Open `main.py` and confirm the include lines for `nq_health`, `daily`, `hrms`, `cycle`,
      `dashboard`, `exports` are all still present.
- [ ] Run the test suite on **Python 3.11** (the Dockerfile image) - only 3.10 was available during development.
      CI today only builds/deploys; consider a test step. Tests need the dev Docker stack
      (`docker compose -f docker-compose.dev.yml up -d`; compose is bound to 127.0.0.1).
- [ ] Production requirements now include `PyMySQL`, `DBUtils`; `pytest` moved to `requirements-dev.txt`.
- [ ] Optional hardening: add a `.dockerignore` (`.git`, `.env`, `tests`, `docs`, `venv`, `__pycache__`) so the image
      never contains local secrets or the schema file. Not applied (changes the build context).

## 2. Staging configuration (nothing below is applied by this branch)

- [ ] **Nexus Quant access from the container** - see `docs/deploy_phase4_proposal.md` section 2. The app needs
      `NQ_DB_HOST`, `NQ_DB_LOCAL_PORT`, `NQ_DB_NAME`, `NQ_DB_USER`, `NQ_DB_PASS` and a route to the SSH tunnel.
      Use the READ-ONLY MySQL user. Ask the NQ owner for a column-level grant that excludes the credential columns of `tbl_user`. Staging should point at a NON-production NQ copy if one exists.
- [ ] **Scheduler container** (digest 20:00 IST, metrics 02:00 IST): `python -m backend.jobs.scheduler`. Exactly one per
      environment. Needs the same Mongo + NQ variables. See the proposal for the `deploy.yml` snippet (NOT applied).
- [ ] **Mail is OFF by default.** Set `TIMESNAP_SEND_MAIL=1` only where real emails should go out. On staging leave it
      unset (or point mail at test addresses) so managers are never emailed from staging.
- [ ] Mongo `config` document `{_id: "timesheet"}`: set `pilot_employees` (small list). Everything new is invisible to
      everyone else. Leave `nq_writeback_enabled` false (default).
- [ ] Use a **staging copy** of Mongo for the first run; never point staging at production data.

## 3. First-run steps on staging (in order)

1. Deploy; open `GET /api/health/nq` (logged in) -> `reachable: true`.
2. Run the data backfill once: `python -m backend.jobs.metrics --backfill 90`
   (builds `hours_daily` from legacy + new entries and 90 days of compliance history; creates indexes).
3. Optional: migrate legacy entries for pilot users on a COPY first:
   `python migrate_timesheet_entries.py --uri <copy-uri> --db <copy-db>` (dry run), then add `--apply`.
4. As admin, upload an HRMS export (`/static/timesheet/hrms.html`): preview, check warnings (unknown Muster codes,
   unknown employees), then import. Re-import the same file - it must change nothing.

## 4. Smoke tests (staging, with real roles)

- [ ] Pilot employee: `/static/timesheet/daily.html` loads tasks from NQ, saves, submits; one-task day shows
      "awaiting HRMS" then fills after the HRMS upload.
- [ ] Non-pilot employee: daily link is hidden; old timesheet grid works exactly as before (create, submit, manager
      approve/reject, Excel upload/export, history).
- [ ] Manager: reconciliation, cycle review (approve only after the cycle ends; locked days cannot be edited, even by
      adding entries), dashboard shows only their own projects and team.
- [ ] Partner (Grade PND) / admin: portfolio and the three Excel exports download and open without formula prompts.
- [ ] Employee (no reportees) gets 403 on `/hrms/reco`, `/dashboard/*`, `/exports/*`.
- [ ] Stop NQ (or break the tunnel): daily page still loads with the "may be out of date" banner; dashboards still load.
- [ ] Digest dry run: `python -m backend.jobs.scheduler --run-now --dry-run-dir out` and read the HTML.
- [ ] Review `email_log`, `job_runs`, `export_audit`, `cycle_reviews` for sensible rows.

## 5. Known limits to accept (or fix) before production

- Metrics and compliance reflect **pilot** employees for day-level data; legacy hours are included in project hours
  (flagged by source). Team load assumes 100% allocation (NQ has no allocation column).
- `tbl_projects.project_manager` is assumed to hold NQ user ids - verify against live data (manager dashboards depend
  on it).
- Approved/locked cycles are final for the employee; only an admin can unlock (audited).
- Four legacy routes (`/timesheet/save-draft`, `/draft/{id}`, `/submission-status/{id}`, `/submit`) are declared in both
  `main.py` and `backend/timesheet/router.py` already on `main`. Not caused by this branch; worth cleaning up separately.
- A crash between "claiming" an email and recording it leaves that mail marked `sending` (never re-sent). This is
  deliberate (at-most-once).

## 6. Production gate

- [ ] Staging ran for at least one full 10-day cycle including a real HRMS upload, one digest and one cycle approval.
- [ ] Production Mongo backup taken. Secrets added to GitHub (NQ_*, and mail flags if wanted).
- [ ] Merge `staging` -> `main` only after the blockers in section 0 are closed. Rollback = stop the scheduler container
      and redeploy the previous image (all changes are additive; legacy data is only read).
