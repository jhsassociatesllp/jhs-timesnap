# Phase 4 deployment proposal (NOT applied)

Nothing in `.github/workflows/deploy.yml` has been changed. This file describes what would
need to change so a person with infrastructure access can review and apply it.

## 1. A second container for the scheduler

The 20:00 IST digest must run as its **own process**, not inside every uvicorn worker. The simplest
fit for the existing pipeline is a second container started from the **same image** with a different
command. In `deploy.yml`, after the existing `docker run ... "$IMAGE"` block, add (sketch):

```bash
SCHED_NAME="${APP_NAME}_scheduler"
docker stop "$SCHED_NAME" || true
docker rm -f "$SCHED_NAME" || true
docker run -d \
  --name "$SCHED_NAME" \
  --restart unless-stopped \
  -e APP_ENV="$ENV" \
  -e MONGO_CONNECTION_STRING="${{ secrets.MONGO_CONNECTION_STRING }}" \
  -e SECRET_KEY="${{ secrets.SECRET_KEY }}" \
  -e TIMESNAP_SEND_MAIL=1 \
  -e OUTLOOK_EMAIL="${{ secrets.OUTLOOK_EMAIL }}" \
  -e OUTLOOK_APP_PASSWORD="${{ secrets.OUTLOOK_APP_PASSWORD }}" \
  -e GRAPH_TENANT_ID="${{ secrets.GRAPH_TENANT_ID }}" \
  -e GRAPH_CLIENT_ID="${{ secrets.GRAPH_CLIENT_ID }}" \
  -e GRAPH_CLIENT_SECRET="${{ secrets.GRAPH_CLIENT_SECRET }}" \
  -e GRAPH_SENDER="${{ secrets.GRAPH_SENDER }}" \
  -e APP_BASE_URL="${{ secrets.APP_BASE_URL }}" \
  "$IMAGE" python -m backend.jobs.scheduler
```

* Staging should leave `TIMESNAP_SEND_MAIL` unset so staging can never email real managers.
* Only ONE scheduler container should exist per environment. If two are ever started the
  `job_runs` unique index and the `email_log` key still guarantee a digest is sent once.
* The web container does **not** need `TIMESNAP_SEND_MAIL` for the digest, but the
  "Remind pending" button sends mail from the web container: it needs the same mail variables
  and `TIMESNAP_SEND_MAIL=1` if reminders should really be sent.

## 2. Nexus Quant access from the containers (needed by Phases 1–4)

`deploy.yml` passes no `NQ_*` variables today. The app code connects to MySQL at
`NQ_DB_HOST:NQ_DB_LOCAL_PORT`. Production design (CLAUDE.md): an autossh/systemd tunnel on server A
listens on `127.0.0.1:${NQ_DB_LOCAL_PORT}`. A container cannot see the host's `127.0.0.1`, so one of:

* run the web container with `--network host` (and drop `-p`), **or**
* bind the tunnel to the Docker bridge address and set `NQ_DB_HOST` to it
  (`-L 172.17.0.1:3307:127.0.0.1:3306`, then `-e NQ_DB_HOST=172.17.0.1`), **or**
* `--add-host=host.docker.internal:host-gateway` with the tunnel bound to `0.0.0.0`
  restricted by a firewall rule (least preferred).

Variables to add as GitHub secrets and pass with `-e`:
`NQ_DB_HOST`, `NQ_DB_LOCAL_PORT`, `NQ_DB_NAME`, `NQ_DB_USER`, `NQ_DB_PASS`
(and `NQ_WB_USER`, `NQ_WB_PASS` only if write-back is ever enabled).

The NQ DB user should be the read-only user; ask the NQ owner to restrict it with a column-level
grant that excludes the credential columns of `tbl_user`.

## 3. NQ write-back stays OFF

`config.nq_writeback_enabled` defaults to false, so re-estimates are stored in Timesnap
(`cycle_reviews`) only. To enable it later: the NQ owner creates a MySQL user with
`GRANT UPDATE (end_date) ON jhsdb.tbl_project_tasks`, you set `NQ_WB_USER` / `NQ_WB_PASS`, and set
`nq_writeback_enabled: true` in the Mongo `config` document `{_id: "timesheet"}`.

## 4. One-time data setup (per environment)

In the Mongo `config` document `{_id: "timesheet"}` set `pilot_employees` (list of EmpIDs). Optional:
`hrms_status_codes` (extra Muster codes), `rag` (RAG thresholds), `holidays` (filled from HRMS uploads).

## 5. Rollback

All new endpoints, collections and the scheduler are additive. To roll back: stop the scheduler
container and redeploy the previous image. The legacy timesheet grid, `Timesheet_data` and the
existing approval flow are untouched by Phases 2–4.

## 6. Phase 5 additions (dashboards) - NOT applied

* **Nightly metrics job** runs inside the SAME scheduler container (`python -m backend.jobs.scheduler`):
  02:00 IST -> `hours_daily`, `dashboard_daily`, `project_metrics`, `team_snapshot`. So the scheduler
  container needs the **NQ_*** variables and the tunnel access described in section 2 (the digest alone did not).
  If NQ is unreachable the job retries every 10 minutes; the web dashboards keep showing the last snapshot.
* **First run / backfill** (once per environment, from any container with the same env):
  `python -m backend.jobs.metrics --backfill 90`  (builds the full `hours_daily` history from `timesheet_entries`
  and the legacy `Timesheet_data`, and 90 days of compliance history). Project / team snapshots only exist from
  the first run onward - NQ cannot provide historic states.
* No new secrets or ports. New collections: `hours_daily`, `project_metrics`, `dashboard_daily`, `team_snapshot`,
  `export_audit` (all additive; the legacy collections are only read).
* Optional `config` keys: `rag` (thresholds), `portfolio` access follows Grade "PND" + timesheet admins.
* Rollback: stop the scheduler container; the dashboard pages simply show "No snapshot yet".
