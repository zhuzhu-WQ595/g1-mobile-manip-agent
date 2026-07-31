import pytest

from contracts.execution import (
    ExecutionError,
    ExecutionEvent,
    ExecutionRequest,
    ExecutionResult,
    ExecutionStatus,
    normalize_execution_status,
)
from contracts.robot import ActionStatus, RobotResult, RobotState


def test_execution_request_and_event_round_trip():
    request = ExecutionRequest(
        capability="workspace.read_file",
        execution_target="local_toolkit",
        arguments={"path": "README.md"},
        execution_id="exec_test",
    )
    event = request.event(ExecutionStatus.SUCCEEDED, result="content")

    restored_request = ExecutionRequest.from_dict(request.to_dict())
    restored_event = ExecutionEvent.from_dict(event.to_dict())

    assert restored_request == request
    assert restored_event == event
    assert restored_event.terminal is True
    assert restored_event.succeeded is True


def test_failed_execution_requires_structured_error():
    request = ExecutionRequest("workspace.read_file", "local_toolkit")

    with pytest.raises(ValueError, match="require an error"):
        request.event(ExecutionStatus.FAILED, result="failed")

    error = ExecutionError("PermissionError", "denied", retryable=False)
    event = request.event(ExecutionStatus.FAILED, result="failed", error=error)

    assert event.error == error
    assert event.to_dict()["error"]["code"] == "PermissionError"


def test_execution_result_accepts_only_terminal_event():
    request = ExecutionRequest("robot.robot_move", "robot_gateway")

    with pytest.raises(ValueError, match="non-terminal"):
        ExecutionResult.from_event(request.event(ExecutionStatus.RUNNING, progress=0.5))

    result = ExecutionResult.from_event(
        request.event(ExecutionStatus.SUCCEEDED, progress=1.0, result={"distance": 0.2})
    )

    assert result.status is ExecutionStatus.SUCCEEDED
    assert result.result == {"distance": 0.2}


@pytest.mark.parametrize(
    ("action_status", "execution_status"),
    [
        (ActionStatus.PENDING, ExecutionStatus.ACCEPTED),
        (ActionStatus.RUNNING, ExecutionStatus.RUNNING),
        (ActionStatus.SUCCEEDED, ExecutionStatus.SUCCEEDED),
        (ActionStatus.FAILED, ExecutionStatus.FAILED),
        (ActionStatus.CANCELLED, ExecutionStatus.CANCELLED),
        (ActionStatus.TIMED_OUT, ExecutionStatus.TIMED_OUT),
    ],
)
def test_robot_result_maps_to_execution_status(action_status, execution_status):
    result = RobotResult(
        ok=action_status not in {ActionStatus.FAILED, ActionStatus.TIMED_OUT},
        message=action_status.value,
        state=RobotState(),
        action_id="action_test",
        status=action_status,
        progress=1.0 if action_status is ActionStatus.SUCCEEDED else 0.5,
        error="robot_error" if action_status is ActionStatus.FAILED else None,
    )

    event = result.to_execution_event("robot.robot_move")

    assert event.execution_id == "action_test"
    assert event.status is execution_status
    assert event.execution_target == "robot_gateway"
    assert event.observation["mode"] == "simulated"


def test_legacy_status_values_normalize_to_execution_status():
    assert normalize_execution_status("ok") is ExecutionStatus.SUCCEEDED
    assert normalize_execution_status("error") is ExecutionStatus.FAILED
    assert normalize_execution_status("pending") is ExecutionStatus.ACCEPTED
