# Nexus Quant tunnel on the server (one-time setup)

Why: the staging and production containers on server A must read Nexus Quant (server B). Without this, My day, Review,
the dashboards and the Project tracker show "Nexus Quant is unavailable". A tunnel started by hand (or on a laptop)
disappears; this one is a service that reconnects by itself after a drop or a reboot.

How it fits: `autossh` on server A listens on the Docker bridge address `172.17.0.1:3307` and forwards to MySQL on server B.
`deploy.yml` starts the web container with `--add-host=host.docker.internal:host-gateway` (that name is the bridge address) and
`NQ_DB_HOST=host.docker.internal`. Both staging and production use the same tunnel. Nothing listens on the public network.

## 1. On server A (needs root; once)

```bash
sudo apt-get install -y autossh
sudo mkdir -p /etc/nq-tunnel && sudo chmod 700 /etc/nq-tunnel
sudo cp deploy/nq-tunnel.env.example /etc/nq-tunnel/nq-tunnel.env      # then edit the host, user and ports
sudo cp <the SSH private key for the tunnel user on server B> /etc/nq-tunnel/id_nq
sudo chmod 600 /etc/nq-tunnel/id_nq /etc/nq-tunnel/nq-tunnel.env
sudo cp deploy/nq-tunnel.service /etc/systemd/system/nq-tunnel.service
sudo systemctl daemon-reload && sudo systemctl enable --now nq-tunnel
```

Check: `systemctl status nq-tunnel` shows active, and `ss -ltn | grep 3307` shows `172.17.0.1:3307`.
Test the database from inside Docker (use the read-only user):
`docker run --rm --add-host=host.docker.internal:host-gateway mysql:8 mysql -h host.docker.internal -P 3307 -u <NQ_DB_USER> -p -e "select 1"`

Use a key that can only open this tunnel (on server B, restrict it with `permitopen="127.0.0.1:3306"` in `authorized_keys`).
If your server's Docker bridge is not 172.17.0.1, run `ip addr show docker0` and set `NQ_BIND_ADDR` to that address.

## 2. GitHub repository secrets (Settings > Secrets and variables > Actions)

| Secret | Value |
|---|---|
| `NQ_DB_LOCAL_PORT` | `3307` (same as in the env file) |
| `NQ_DB_NAME` | the NQ database name (`jhsdb`) |
| `NQ_DB_USER` | the READ-ONLY MySQL user (SELECT only; ideally without the credential columns of `tbl_user`) |
| `NQ_DB_PASS` | its password |

Enter these yourself in GitHub; do not paste them anywhere else. Leave write-back (`NQ_WB_*`) unset.

## 3. Deploy and check

Push to `staging` (or re-run the "Build, Push & Deploy" workflow). Open the staging site, My day: the "Nexus Quant is unavailable"
banner is gone and tasks are listed. If it remains: `docker logs jhs_timesnap_staging | grep -i "NQ unavailable"` shows why
(wrong user or password, tunnel down, wrong port).

Staging and production share one NQ (read-only). Mail stays off unless `TIMESNAP_SEND_MAIL=1` is set.
