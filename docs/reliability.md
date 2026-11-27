# Running Kamerton behind a reverse proxy on Linux

Kamerton's Docker health check reaches the console over the container's own loopback.
If Docker cannot bind the published port, the reverse proxy may return 502 while
Docker reports the console as healthy. This can happen at boot if the host gets its
LAN address over DHCP. `docker port` shows Docker's active publication, and a request
from the proxy host verifies that traffic can reach it.

## Start after the address is available

For an NPM deployment managed directly with Compose on a systemd host, use
[the systemd override](../deploy/compose.systemd.yml). It leaves startup and
recovery to the host timer and routes container output to the host journal.
Use Compose 2.24.4 or later and a stable host IP, for example a DHCP reservation.
Keep the upstream port restricted to the proxy.

1. Install `deploy/kamerton_reconcile.py` at `/usr/local/libexec/kamerton-reconcile.py`
   and the two `deploy/kamerton-reconcile.*` units in `/etc/systemd/system/`.
2. Create `/etc/kamerton/reconcile.env` with values for the existing deployment.
   `COMPOSE_FILE` uses `:` as the separator on Linux. Set `COMPOSE_PROJECT_NAME`
   if the installation already has a custom project name. Resolve the configuration
   with the same files, project name and environment as the running stack.

   ```dotenv
   KAMERTON_PROJECT_DIR=/srv/kamerton
   KAMERTON_PUBLISH_IP=192.0.2.10
   KAMERTON_PUBLISH_PORT=8812
   KAMERTON_ENV_FILE=/srv/kamerton/.env.npm
   COMPOSE_FILE=/srv/kamerton/docker-compose.npm.yml:/srv/kamerton/deploy/compose.systemd.yml
   ```

3. Verify the resolved Compose configuration and recreate the service once to
   apply the restart policy and log driver. Use the already built image. Then run
   `systemctl daemon-reload` and `systemctl enable --now kamerton-reconcile.timer`.
   Run `systemctl start kamerton-reconcile.service` for an immediate check.

The check runs approximately every 15 seconds. It waits for the configured IP,
starts a stopped service, restores a missing Docker port mapping by recreating the
container, and restarts a console marked unhealthy. An HTTP check from another
machine through the public HTTPS endpoint covers the proxy and TLS as well.
With one backend, restarts still interrupt connections while the console starts.

For intentional shutdowns, deployment or migration, stop `kamerton-reconcile.timer`
and `kamerton-reconcile.service` before changing the stack, then reenable the timer
afterward if the service should run. Keep the logging and restart policy in the
effective manifest when using a deployment manager.

## Keep logs across container replacement

Enable persistent `systemd-journald` storage on the Docker host and set its size
limit for the desired retention. The stable tag allows querying previous container
IDs and boots. Copy existing `json-file` logs before the first recreation, because
Docker removes those logs with the old container. [Docker journald logging driver](https://docs.docker.com/engine/logging/drivers/journald/)

```bash
journalctl CONTAINER_TAG=kamerton
journalctl -u kamerton-reconcile.service
journalctl -u docker -b -1
```

Keep the proxy's upstream error log on persistent storage on its own host as well.
Restrict log access and avoid recording authorization headers, request bodies and
URLs containing sensitive parameters. The console's in-memory event list is a
separate view of recent application events.
