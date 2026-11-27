"""Start and reconcile a single Kamerton Compose service on a systemd host."""

import json
import os
import socket
import subprocess
import sys
from pathlib import Path


SERVICE = "kamerton"
CONTAINER_PORT = "8080/tcp"
INSPECT_FORMAT = (
    '{"state":{{json .State}},"ports":{{json .NetworkSettings.Ports}},'
    '"requested_ports":{{json .HostConfig.PortBindings}}}'
)


def capture(*command: str) -> str:
    return subprocess.check_output(command, text=True, timeout=10).strip()


def run(*command: str) -> None:
    subprocess.run(command, check=True, timeout=60)


def reconcile(project_dir: Path, address: str, port: str) -> None:
    interfaces = json.loads(capture("ip", "-j", "-4", "address", "show", "up"))
    if not any(a.get("local") == address for i in interfaces for a in i.get("addr_info", [])):
        print(f"Waiting for host address {address}")
        return

    compose = ["docker", "compose", "--project-directory", str(project_dir)]
    if env_file := os.environ.get("KAMERTON_ENV_FILE"):
        compose.extend(("--env-file", env_file))
    container = capture(*compose, "ps", "--all", "--quiet", SERVICE)
    if len(container.splitlines()) > 1:
        raise RuntimeError(f"Expected a single {SERVICE} container")

    up = [*compose, "up", "-d", "--no-deps", "--no-build", "--pull", "never"]
    if not container:
        print(f"Creating {SERVICE}", flush=True)
        run(*up, "--no-recreate", SERVICE)
        return

    details = json.loads(capture("docker", "inspect", "--format", INSPECT_FORMAT, container))
    state = details["state"]["Status"]
    if state in ("created", "exited"):
        print(f"Starting {SERVICE} ({state})", flush=True)
        run(*up, "--no-recreate", SERVICE)
        return
    if state in ("paused", "restarting", "removing"):
        return
    if state != "running":
        raise RuntimeError(f"Unexpected {SERVICE} container state: {state}")

    health = details["state"].get("Health", {}).get("Status")
    if health == "starting":
        return

    binding = {"HostIp": address, "HostPort": port}
    requested = (details["requested_ports"] or {}).get(CONTAINER_PORT) or []
    published = (details["ports"] or {}).get(CONTAINER_PORT) or []
    if binding not in requested or (published and binding not in published):
        raise RuntimeError(f"Check the configured port binding for {SERVICE}")
    if not published:
        print(f"Recreating {SERVICE}: Docker lost the requested port binding", flush=True)
        run(*up, "--force-recreate", SERVICE)
        return
    if health == "unhealthy":
        print(f"Restarting {SERVICE} after failed Docker health checks", flush=True)
        run("docker", "restart", container)
        return

    # Report a broken route without restarting a healthy backend behind a firewall.
    with socket.create_connection((address, int(port)), timeout=2):
        pass


def main() -> int:
    try:
        reconcile(
            Path(os.environ["KAMERTON_PROJECT_DIR"]),
            os.environ["KAMERTON_PUBLISH_IP"],
            os.environ.get("KAMERTON_PUBLISH_PORT", "8812"),
        )
    except (KeyError, OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        print(f"Kamerton recovery check failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
