from __future__ import annotations

import json
import threading

import pytest

from agent.agent_loop import Agent
from agent.capabilities import CAPABILITY_REGISTRY
from agent.models import DemoModel
from agent.permissions import check_tool_call
from agent.scheduling import ExecutionDispatcher
from contracts.execution import ExecutionRequest, ExecutionStatus
from services.demo_server import DemoServiceHTTPServer
from services.registry import ServiceRegistry


@pytest.fixture
def demo_service(monkeypatch):
    server = DemoServiceHTTPServer(("127.0.0.1", 0))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    monkeypatch.setenv("REMOTE_SERVICES", json.dumps({"demo": base_url}))
    try:
        yield base_url
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _request(operation: str, payload: dict | None = None, service: str = "demo") -> ExecutionRequest:
    capability = CAPABILITY_REGISTRY.get("invoke_remote_service")
    return ExecutionRequest(
        capability=capability.name,
        execution_target=capability.execution_target.value,
        arguments={"service": service, "operation": operation, "payload": payload or {}},
    )


def test_dispatcher_calls_remote_service_over_http(demo_service):
    event = ExecutionDispatcher(handlers={}).dispatch(_request("inspect"))

    assert event.status is ExecutionStatus.SUCCEEDED
    assert event.execution_target == "remote_service"
    assert event.result["service"] == "self-test-demo"
    assert event.metadata["tool"] == "invoke_remote_service"


def test_remote_service_returns_structured_business_failure(demo_service):
    event = ExecutionDispatcher(handlers={}).dispatch(_request("missing"))

    assert event.status is ExecutionStatus.FAILED
    assert event.error is not None
    assert event.error.code == "unsupported_operation"
    assert event.result.startswith("ERROR: unsupported_operation:")


def test_dispatcher_rejects_unconfigured_remote_service(monkeypatch):
    monkeypatch.setenv("REMOTE_SERVICES", "{}")

    event = ExecutionDispatcher(handlers={}).dispatch(_request("inspect", service="unknown"))

    assert event.status is ExecutionStatus.FAILED
    assert event.error is not None
    assert event.error.code == "PermissionError"
    assert "not configured" in event.error.message


def test_remote_permission_rejects_url_instead_of_service_name():
    with pytest.raises(PermissionError, match="symbolic service name"):
        check_tool_call(
            "invoke_remote_service",
            {"service": "http://127.0.0.1:9020", "operation": "inspect"},
        )


def test_service_registry_rejects_non_http_url(monkeypatch):
    monkeypatch.setenv("REMOTE_SERVICES", json.dumps({"unsafe": "file:///tmp/data"}))

    with pytest.raises(ValueError, match="HTTP or HTTPS"):
        ServiceRegistry.from_env()


def test_demo_model_runs_remote_service_through_agent(demo_service, monkeypatch):
    monkeypatch.setattr("agent.agent_loop.record_tool_event", lambda event: None)

    trace = Agent(DemoModel()).run_turn_with_trace(
        'call service demo operation echo :: {"message": "hello"}'
    )

    assert trace["events"][0]["status"] == "succeeded"
    assert trace["events"][0]["execution_target"] == "remote_service"
    assert trace["events"][0]["result"] == {"echo": {"message": "hello"}}
    assert "hello" in trace["answer"]
