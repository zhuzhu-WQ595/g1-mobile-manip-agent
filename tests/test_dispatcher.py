from __future__ import annotations

import pytest

from agent.capabilities import CAPABILITY_REGISTRY
from agent.scheduling import ExecutionDispatcher
from contracts.execution import ExecutionRequest, ExecutionStatus


def _request(tool_name: str, **arguments: object) -> ExecutionRequest:
    capability = CAPABILITY_REGISTRY.get(tool_name)
    return ExecutionRequest(
        capability=capability.name,
        execution_target=capability.execution_target.value,
        arguments=arguments,
    )


@pytest.mark.parametrize(
    ("tool_name", "expected_target"),
    [
        ("get_workspace_summary", "local_toolkit"),
        ("list_tasks", "agent_state"),
        ("robot_get_status", "robot_gateway"),
    ],
)
def test_dispatcher_routes_registered_targets(tool_name, expected_target):
    dispatcher = ExecutionDispatcher(handlers={tool_name: lambda: f"ran:{tool_name}"})

    event = dispatcher.dispatch(_request(tool_name))

    assert event.status is ExecutionStatus.SUCCEEDED
    assert event.execution_target == expected_target
    assert event.result == f"ran:{tool_name}"
    assert event.metadata["tool"] == tool_name


def test_dispatcher_rejects_target_mismatch():
    request = _request("get_workspace_summary")
    invalid_request = ExecutionRequest(
        capability=request.capability,
        execution_target="robot_gateway",
    )

    event = ExecutionDispatcher(handlers={}).dispatch(invalid_request)

    assert event.status is ExecutionStatus.FAILED
    assert event.error is not None
    assert event.error.code == "ValueError"
    assert "requires target local_toolkit" in event.error.message


def test_dispatcher_returns_structured_handler_error():
    def fail() -> str:
        raise RuntimeError("device unavailable")

    event = ExecutionDispatcher(handlers={"robot_get_status": fail}).dispatch(
        _request("robot_get_status")
    )

    assert event.status is ExecutionStatus.FAILED
    assert event.error is not None
    assert event.error.code == "RuntimeError"
    assert event.error.retryable is True
    assert event.result == "ERROR: RuntimeError: device unavailable"


def test_dispatcher_stops_before_handler_when_permission_is_denied(monkeypatch):
    called = False

    def handler() -> str:
        nonlocal called
        called = True
        return "must not run"

    monkeypatch.setattr(
        "agent.scheduling.dispatcher.check_tool_call",
        lambda name, arguments: (_ for _ in ()).throw(PermissionError("denied")),
    )

    event = ExecutionDispatcher(handlers={"get_workspace_summary": handler}).dispatch(
        _request("get_workspace_summary")
    )

    assert called is False
    assert event.status is ExecutionStatus.FAILED
    assert event.error is not None
    assert event.error.code == "PermissionError"


def test_dispatcher_rejects_unknown_capability():
    request = ExecutionRequest("unknown.tool", "local_toolkit")

    event = ExecutionDispatcher(handlers={}).dispatch(request)

    assert event.status is ExecutionStatus.FAILED
    assert event.error is not None
    assert event.error.code == "KeyError"
    assert "Unknown capability" in event.error.message
