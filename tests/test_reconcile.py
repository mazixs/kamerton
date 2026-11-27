import json
from pathlib import Path
from unittest.mock import MagicMock, Mock

import pytest

from deploy import kamerton_reconcile as agent


ADDRESS = "192.0.2.10"
PORT = "8812"
BINDING = {"HostIp": ADDRESS, "HostPort": PORT}
UP = (
    "docker", "compose", "--project-directory", "test-project", "up",
    "-d", "--no-deps", "--no-build", "--pull", "never",
)


@pytest.fixture
def docker(monkeypatch):
    monkeypatch.delenv("KAMERTON_ENV_FILE", raising=False)
    execute = Mock()
    probe = MagicMock()
    monkeypatch.setattr(agent, "run", execute)
    monkeypatch.setattr(agent.socket, "create_connection", probe)
    return execute, probe


def test_waits_for_the_exact_host_address_before_touching_docker(monkeypatch, docker):
    capture = Mock(return_value=json.dumps([{"addr_info": [{"local": "192.0.2.11"}, {}]}]))
    monkeypatch.setattr(agent, "capture", capture)

    agent.reconcile(Path("test-project"), ADDRESS, PORT)

    capture.assert_called_once_with("ip", "-j", "-4", "address", "show", "up")
    docker[0].assert_not_called()


def test_can_create_the_service_bound_to_loopback(monkeypatch, docker):
    def capture(*command):
        if command[0] == "ip":
            addresses = [] if "global" in command else [{"local": "127.0.0.1", "scope": "host"}]
            return json.dumps([{"addr_info": addresses}])
        return ""

    monkeypatch.setattr(agent, "capture", capture)

    agent.reconcile(Path("test-project"), "127.0.0.1", PORT)

    docker[0].assert_called_once_with(*UP, "--no-recreate", "kamerton")


@pytest.mark.parametrize(("state", "health", "published", "expected"), [
    ("exited", "unhealthy", [], (*UP, "--no-recreate", "kamerton")),
    ("running", "healthy", [], (*UP, "--force-recreate", "kamerton")),
    ("running", "unhealthy", [BINDING], ("docker", "restart", "container-id")),
    ("running", "healthy", [BINDING], None),
    ("running", "starting", [BINDING], None),
])
def test_reconciles_container_without_disrupting_a_healthy_backend(
    monkeypatch, docker, state, health, published, expected,
):
    execute, probe = docker
    details = {
        "state": {"Status": state, "Health": {"Status": health}},
        "ports": {agent.CONTAINER_PORT: published},
        "requested_ports": {agent.CONTAINER_PORT: [BINDING]},
    }
    capture = Mock(side_effect=[
        json.dumps([{"addr_info": [{"local": ADDRESS}]}]), "container-id", json.dumps(details),
    ])
    monkeypatch.setattr(agent, "capture", capture)

    agent.reconcile(Path("test-project"), ADDRESS, PORT)

    if expected:
        execute.assert_called_once_with(*expected)
    else:
        execute.assert_not_called()
    if state == "running" and health == "healthy" and published:
        probe.assert_called_once_with((ADDRESS, int(PORT)), timeout=2)
    else:
        probe.assert_not_called()
