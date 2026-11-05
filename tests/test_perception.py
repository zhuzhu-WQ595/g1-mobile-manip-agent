from __future__ import annotations

import json
import threading

import pytest

from agent.capabilities import CAPABILITY_REGISTRY
from agent.execution import GoalRunner, ROBOT_GOAL_TOOLS, RobotFeedbackVerifier
from agent.models import DemoModel
from agent.robot.policy import check_motion_against_latest_perception
from agent.scheduling import DISPATCHER, ExecutionDispatcher
from contracts.execution import ExecutionRequest, ExecutionStatus
from contracts.observation import Observation
from services.perception import PerceptionServiceHTTPServer, SimulatedPerceptionService


@pytest.fixture
def perception_server(monkeypatch):
    servers: list[tuple[PerceptionServiceHTTPServer, threading.Thread]] = []
    # The "clear" scene consults real robot lidar via the gateway; stub it so
    # unit tests don't depend on a live ROBOT_BASE_URL service.
    monkeypatch.setattr(
        SimulatedPerceptionService,
        "_get_robot_state",
        lambda self: {"front_obstacle_m": 10.0},
    )

    def start(scene: str) -> str:
        server = PerceptionServiceHTTPServer(
            ("127.0.0.1", 0),
            SimulatedPerceptionService(scene),
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        servers.append((server, thread))
        base_url = f"http://127.0.0.1:{server.server_port}"
        monkeypatch.setenv("REMOTE_SERVICES", json.dumps({"perception": base_url}))
        return base_url

    yield start

    for server, thread in servers:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _perception_request(tool_name: str, **arguments: object) -> ExecutionRequest:
    capability = CAPABILITY_REGISTRY.get(tool_name)
    return ExecutionRequest(
        capability=capability.name,
        execution_target=capability.execution_target.value,
        arguments=arguments,
    )


def test_observation_contract_round_trip():
    observation = Observation(
        source="front_camera",
        path_clear=False,
        obstacles=({"label": "box", "distance_m": 0.2},),
        confidence=0.9,
    )

    restored = Observation.from_dict(observation.to_dict())

    assert restored == observation


@pytest.mark.parametrize(
    ("scene", "expected_status", "path_clear", "error_code"),
    [
        ("clear", ExecutionStatus.SUCCEEDED, True, None),
        ("blocked", ExecutionStatus.SUCCEEDED, False, None),
        ("failure", ExecutionStatus.FAILED, None, "sensor_unavailable"),
    ],
)
def test_perception_service_returns_structured_feedback(
    perception_server,
    scene,
    expected_status,
    path_clear,
    error_code,
):
    perception_server(scene)
    event = ExecutionDispatcher(handlers={}).dispatch(
        _perception_request("perception_check_path", direction="forward", distance=0.2)
    )

    assert event.status is expected_status
    if expected_status is ExecutionStatus.SUCCEEDED:
        assert event.observation is not None
        assert event.observation["path_clear"] is path_clear
        assert event.result["path_clear"] is path_clear
    else:
        assert event.error is not None
        assert event.error.code == error_code


class PerceptionThenMoveModel:
    def __init__(self) -> None:
        self.calls = 0

    def complete(self, messages, tools, system_prompt=None):
        self.calls += 1
        if self.calls == 1:
            return {
                "type": "tool_calls",
                "tool_calls": [
                    {
                        "id": "observe",
                        "name": "perception_check_path",
                        "arguments": {"direction": "forward", "distance": 0.2},
                    }
                ],
            }
        if self.calls == 2:
            return {
                "type": "tool_calls",
                "tool_calls": [
                    {
                        "id": "move",
                        "name": "robot_move",
                        "arguments": {"distance": 0.2, "direction": "forward", "speed": 0.1},
                    }
                ],
            }
        return {"type": "message", "text": "Execution finished from observed feedback."}


def test_clear_perception_allows_goal_runner_motion(perception_server, monkeypatch):
    perception_server("clear")
    monkeypatch.setenv("ROBOT_MODE", "simulated")
    monkeypatch.setattr("agent.execution.runner.record_tool_event", lambda event: None)
    monkeypatch.setitem(
        DISPATCHER.handlers,
        "robot_move",
        lambda **arguments: json.dumps({"status": "succeeded", "distance": arguments["distance"]}),
    )

    result = GoalRunner(
        PerceptionThenMoveModel(),
        max_steps=3,
        tool_names={"perception_check_path", "robot_move"},
    ).run("check the path and move forward 0.2m only if it is clear")

    assert result["status"] == "completed"
    assert [event["status"] for event in result["events"]] == ["succeeded", "succeeded"]


@pytest.mark.parametrize("scene", ["blocked", "failure"])
def test_unsafe_perception_blocks_goal_runner_motion(perception_server, monkeypatch, scene):
    perception_server(scene)
    monkeypatch.setenv("ROBOT_MODE", "simulated")
    monkeypatch.setattr("agent.execution.runner.record_tool_event", lambda event: None)
    monkeypatch.setitem(
        DISPATCHER.handlers,
        "robot_move",
        lambda **arguments: (_ for _ in ()).throw(AssertionError("motion handler must not run")),
    )

    result = GoalRunner(
        PerceptionThenMoveModel(),
        max_steps=3,
        tool_names={"perception_check_path", "robot_move"},
    ).run("check the path and move forward 0.2m only if it is clear")

    assert result["status"] == "blocked"
    assert result["stop_reason"] == "permission_denied"
    assert result["events"][-1]["tool"] == "robot_move"
    assert result["events"][-1]["status"] == "failed"
    assert "Robot motion blocked" in result["events"][-1]["result"]


def test_path_check_only_authorizes_matching_next_motion():
    observation = Observation(source="front_sensor", path_clear=True).to_dict()
    events = [
        {
            "tool": "perception_check_path",
            "status": "succeeded",
            "arguments": {"direction": "forward", "distance": 0.2},
            "observation": observation,
        }
    ]

    with pytest.raises(PermissionError, match="exceeds the latest perception check"):
        check_motion_against_latest_perception(
            "robot_move",
            {"direction": "forward", "distance": 0.5},
            events,
        )

    events.append({"tool": "robot_move", "status": "succeeded", "arguments": {"distance": 0.2}})
    with pytest.raises(PermissionError, match="new perception check"):
        check_motion_against_latest_perception(
            "robot_move",
            {"direction": "forward", "distance": 0.1},
            events,
        )


def test_demo_goal_moves_only_after_clear_perception(perception_server, monkeypatch):
    perception_server("clear")
    monkeypatch.setenv("ROBOT_MODE", "simulated")
    monkeypatch.setattr("agent.execution.runner.record_tool_event", lambda event: None)
    monkeypatch.setitem(
        DISPATCHER.handlers,
        "robot_move",
        lambda **arguments: json.dumps(
            {
                "action_id": "action_demo",
                "status": "succeeded",
                "ok": True,
                "message": "move completed",
                "progress": 1.0,
                "state": {"stopped": True, "x": arguments["distance"]},
                "data": {},
            }
        ),
    )

    result = GoalRunner(
        DemoModel(),
        max_steps=4,
        tool_names=ROBOT_GOAL_TOOLS,
        completion_verifier=RobotFeedbackVerifier(),
    ).run("Check the path and move forward 0.2 meters only if it is clear.")

    assert result["status"] == "completed"
    assert result["stop_reason"] == "feedback_verified"
    assert [event["tool"] for event in result["events"]] == [
        "perception_check_path",
        "robot_move",
    ]


def test_demo_goal_withholds_motion_when_perception_is_blocked(perception_server, monkeypatch):
    perception_server("blocked")
    monkeypatch.setenv("ROBOT_MODE", "simulated")
    monkeypatch.setattr("agent.execution.runner.record_tool_event", lambda event: None)
    monkeypatch.setitem(
        DISPATCHER.handlers,
        "robot_move",
        lambda **arguments: (_ for _ in ()).throw(AssertionError("motion handler must not run")),
    )

    result = GoalRunner(
        DemoModel(),
        max_steps=4,
        tool_names=ROBOT_GOAL_TOOLS,
        completion_verifier=RobotFeedbackVerifier(),
    ).run("Check the path and move forward 0.2 meters only if it is clear.")

    assert result["status"] == "completed"
    assert result["stop_reason"] == "feedback_verified"
    assert [event["tool"] for event in result["events"]] == ["perception_check_path"]
    assert result["verifications"][-1]["source"] == "perception_gate"
