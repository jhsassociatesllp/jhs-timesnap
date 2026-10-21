# Seeing real NQ tasks on your machine

The app reads Nexus Quant at `127.0.0.1:${NQ_DB_LOCAL_PORT}`. Locally nothing listens there unless an SSH tunnel is
running, which is why My day says "Project data from Nexus Quant is unavailable".

## Option A: tunnel to the real NQ (read-only user)
1. Save the SSH private key as a file outside the project (e.g. `C:\Users\<you>\.ssh\nq_server_b`) and point
   `NQ_SSH_KEY` in `.env` to that path (remove the pasted key lines from `.env`).
2. In a separate terminal, leave this running while you work (values from `.env`):
   `ssh -N -L 3307:127.0.0.1:3307 -p <NQ_SSH_PORT> -i <key file> <NQ_SSH_USER>@<NQ_SSH_HOST>`
   (left side = `NQ_DB_LOCAL_PORT`, right side = `NQ_DB_REMOTE_PORT`).
3. Restart the app. The app only ever uses the read-only NQ user (`NQ_DB_USER`).
4. Tasks show for the employee code you log in with, when NQ has tasks assigned to that person
   (`tbl_user.emp_id` = your Timesnap employee id).

## Option B: the fake NQ in Docker (no real data)
`docker compose -f docker-compose.dev.yml up -d`, then use the values from `.env.example`
(`NQ_DB_LOCAL_PORT=3308`, `NQ_DB_NAME=jhsdb`, `NQ_DB_USER=nq_ro`, `NQ_DB_PASS=dev_ro_pass`) and log in as `JHS9101`.
