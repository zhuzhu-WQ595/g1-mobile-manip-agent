from __future__ import annotations

import json
import threading
import time

import pytest

from agent.permissions import check_tool_call
from agent.robot.client import HttpRobotAdapter
from agent.robot.tools import ROBOT_TOOL_HANDLERS
from contracts.robot import ActionStatus, RobotCommand
from contracts.robot import RobotResult, RobotState
from robot_runtime import simulator as robot_simulator
from robot_runtime.adapter import RobotRuntimeAdapter, create_runtime_adapter
from robot_runtime.gateway_server import RobotGateway, RobotGatewayHTTPServer
from robot_runtime.simulator import SimulatedRobotAdapter


@pytest.fixture
def http_gateway(tmp_path, monkeypatch):
    monkeypatch.setattr(robot_simulator, "STATE_DIR", tmp_path)
    monkeypatch.setattr(robot_simulator, "STATE_FILE", tmp_path / "robot_state.json")
    gateway = RobotGateway(
        adapter=SimulatedRobotAdapter(time_scale=0.1),
        watchdog_s=5.0,
    )
    server = RobotGatewayHTTPServer(("127.0.0.1", 0), gateway)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield HttpRobotAdapter(f"http://127.0.0.1:{server.server_port}"), gateway
    finally:
        server.shutdown()
        server.server_close()
        gateway.close()
        thread.join(timeout=2)


def wait_for_terminal(adapter: HttpRobotAdapter, action_id: str, timeout: float = 2.0):
    deadline = time.monotonic() + timeout
    result = adapter.get_action(action_id)
    while not result.terminal and time.monotonic() < deadline:
        time.sleep(0.02)
        result = adapter.get_action(action_id)
    return result


def simulated_gateway(tmp_path, monkeypatch) -> SimulatedRobotAdapter:
    monkeypatch.setattr(robot_simulator, "STATE_DIR", tmp_path)
    monkeypatch.setattr(robot_simulator, "STATE_FILE", tmp_path / "robot_state.json")
    return SimulatedRobotAdapter()


def test_simulator_records_action_lifecycle(tmp_path, monkeypatch) -> None:
    gateway = simulated_gateway(tmp_path, monkeypatch)
    command = RobotCommand("move", {"distance": 0.2, "direction": "forward", "speed": 0.2})

    result = gateway.execute(command)
    stored = gateway.get_action(command.action_id)

    assert result.ok is True
    assert result.action_id == command.action_id
    assert result.status is ActionStatus.SUCCEEDED
    assert result.progress == 1.0
    assert stored.to_dict() == result.to_dict()

    recorded_x = result.state.x if result.state else None
    gateway.execute(RobotCommand("move", {"distance": 0.1, "direction": "forward"}))
    assert result.state is not None
    assert result.state.x == recorded_x


def test_emergency_stop_latches_and_rejects_motion(tmp_path, monkeypatch) -> None:
    gateway = simulated_gateway(tmp_path, monkeypatch)

    stopped = gateway.emergency_stop()
    motion = gateway.execute(RobotCommand("move", {"distance": 0.1, "direction": "forward"}))

    assert stopped.ok is True
    assert gateway.get_state().emergency_stopped is True
    assert motion.ok is False
    assert motion.status is ActionStatus.FAILED
    assert "Emergency stop is latched" in (motion.error or "")


def test_http_client_does_not_invent_missing_state(monkeypatch) -> None:
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self) -> bytes:
            return json.dumps({"state": {"mode": "real", "stopped": True}}).encode()

    monkeypatch.setattr("agent.robot.client.urllib.request.urlopen", lambda request, timeout: Response())

    state = HttpRobotAdapter("http://gateway.test").get_state()

    assert state.mode == "real"
    assert state.stopped is True
    assert state.battery_percent is None
    assert state.front_obstacle_m is None
    assert state.emergency_stopped is None


def test_agent_tools_expose_gateway_controls_not_wheel_speed() -> None:
    assert "robot_get_action_status" in ROBOT_TOOL_HANDLERS
    assert "robot_cancel_action" in ROBOT_TOOL_HANDLERS
    assert "robot_emergency_stop" in ROBOT_TOOL_HANDLERS
    assert "robot_set_wheel_speed" not in ROBOT_TOOL_HANDLERS


def test_real_motion_requires_operator_enable(monkeypatch) -> None:
    monkeypatch.setenv("ROBOT_MODE", "http")
    monkeypatch.delenv("ROBOT_ALLOW_MOTION", raising=False)

    check_tool_call("robot_get_status", {})
    check_tool_call("robot_emergency_stop", {})
    with pytest.raises(PermissionError, match="ROBOT_ALLOW_MOTION"):
        check_tool_call("robot_move", {"distance": 0.2})
    with pytest.raises(PermissionError, match="low-level"):
        check_tool_call("robot_set_wheel_speed", {"left": 0.1, "right": 0.1})

    monkeypatch.setenv("ROBOT_ALLOW_MOTION", "1")
    check_tool_call("robot_move", {"distance": 0.2})


def test_http_gateway_runs_action_asynchronously(http_gateway) -> None:
    adapter, _gateway = http_gateway
    command = RobotCommand("move", {"distance": 0.2, "direction": "forward", "speed": 0.2})

    accepted = adapter.execute(command)
    completed = wait_for_terminal(adapter, command.action_id)

    assert accepted.status is ActionStatus.PENDING
    assert completed.status is ActionStatus.SUCCEEDED
    assert completed.progress == 1.0
    assert completed.state is not None
    assert completed.state.x == pytest.approx(0.2)


def test_http_gateway_cancels_running_action(http_gateway) -> None:
    adapter, _gateway = http_gateway
    command = RobotCommand("move", {"distance": 1.0, "direction": "forward", "speed": 0.1})

    adapter.execute(command)
    cancelled = adapter.cancel_action(command.action_id)
    stored = adapter.get_action(command.action_id)

    assert cancelled.status is ActionStatus.CANCELLED
    assert stored.status is ActionStatus.CANCELLED
    assert stored.error == "cancelled_by_request"


def test_http_gateway_times_out_action(http_gateway) -> None:
    adapter, _gateway = http_gateway
    command = RobotCommand(
        "move",
        {"distance": 0.5, "direction": "forward", "speed": 0.1},
        timeout_s=0.05,
    )

    adapter.execute(command)
    result = wait_for_terminal(adapter, command.action_id)

    assert result.status is ActionStatus.TIMED_OUT
    assert result.error == "action_timeout"


def test_http_gateway_emergency_stop_cancels_and_latches(http_gateway) -> None:
    adapter, _gateway = http_gateway
    command = RobotCommand("move", {"distance": 1.0, "direction": "forward", "speed": 0.1})

    adapter.execute(command)
    emergency = adapter.emergency_stop()
    cancelled = adapter.get_action(command.action_id)
    state = adapter.get_state()

    assert emergency.status is ActionStatus.SUCCEEDED
    assert cancelled.status is ActionStatus.CANCELLED
    assert cancelled.error == "emergency_stop"
    assert state.emergency_stopped is True


def test_gateway_watchdog_cancels_unobserved_motion(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(robot_simulator, "STATE_DIR", tmp_path)
    monkeypatch.setattr(robot_simulator, "STATE_FILE", tmp_path / "robot_state.json")
    gateway = RobotGateway(
        adapter=SimulatedRobotAdapter(time_scale=1.0),
        watchdog_s=0.1,
    )
    command = RobotCommand("move", {"distance": 1.0, "direction": "forward", "speed": 0.1})
    try:
        gateway.submit(command)
        time.sleep(0.3)
        result = gateway.get_action(command.action_id)
    finally:
        gateway.close()

    assert result.status is ActionStatus.CANCELLED
    assert result.error == "watchdog_timeout"


def test_simulated_adapter_satisfies_runtime_protocol(tmp_path, monkeypatch) -> None:
    adapter = simulated_gateway(tmp_path, monkeypatch)

    assert isinstance(adapter, RobotRuntimeAdapter)
    assert adapter.name == "simulated"


def test_runtime_adapter_factory_uses_configuration(monkeypatch) -> None:
    monkeypatch.setenv("ROBOT_RUNTIME_ADAPTER", "simulated")

    adapter = create_runtime_adapter(sim_time_scale=0.25)

    assert isinstance(adapter, SimulatedRobotAdapter)
    assert adapter.time_scale == 0.25
    with pytest.raises(RuntimeError, match="Unknown robot runtime adapter"):
        create_runtime_adapter("missing")


def test_gateway_depends_only_on_runtime_adapter_protocol() -> None:
    class RecordingAdapter:
        name = "recording"

        def __init__(self) -> None:
            self.state = RobotState(mode="recording")
            self.executed: list[str] = []
            self.closed = False

        def get_state(self) -> RobotState:
            return self.state

        def execute(self, command: RobotCommand) -> RobotResult:
            self.executed.append(command.action)
            return RobotResult(
                True,
                f"executed {command.action}",
                self.state,
                action_id=command.action_id,
                status=ActionStatus.SUCCEEDED,
            )

        def execute_motion(self, command, cancel_event, feedback) -> RobotResult:
            feedback(0.5)
            return self.execute(command)

        def emergency_stop(self) -> RobotResult:
            return self.execute(RobotCommand("stop"))

        def close(self) -> None:
            self.closed = True

    adapter = RecordingAdapter()
    gateway = RobotGateway(adapter=adapter, watchdog_s=5.0)
    try:
        result = gateway.submit(RobotCommand("speak", {"text": "hello"}))
    finally:
        gateway.close()

    assert result.status is ActionStatus.SUCCEEDED
    assert adapter.executed == ["speak", "stop"]
    assert adapter.closed is True


def test_gateway_shutdown_cancels_active_motion(tmp_path, monkeypatch) -> None:
    adapter = simulated_gateway(tmp_path, monkeypatch)
    gateway = RobotGateway(adapter=adapter, watchdog_s=5.0)
    command = RobotCommand(
        "move",
        {"distance": 1.0, "direction": "forward", "speed": 0.1},
    )

    accepted = gateway.submit(command)
    gateway.close()
    result = gateway.get_action(command.action_id)

    assert accepted.status is ActionStatus.PENDING
    assert result.status is ActionStatus.CANCELLED
    assert result.error == "gateway_shutdown"
    assert adapter.get_state().stopped is True


def test_gateway_converts_runtime_motion_error_to_terminal_failure() -> None:
    class FailingAdapter:
        name = "failing"

        def __init__(self) -> None:
            self.state = RobotState(mode="failing")

        def get_state(self) -> RobotState:
            return self.state

        def execute(self, command: RobotCommand) -> RobotResult:
            self.state.stopped = True
            return RobotResult(True, "stopped", self.state, action_id=command.action_id)

        def execute_motion(self, command, cancel_event, feedback) -> RobotResult:
            raise RuntimeError("bridge disconnected")

        def emergency_stop(self) -> RobotResult:
            return self.execute(RobotCommand("stop"))

        def close(self) -> None:
            return

    gateway = RobotGateway(adapter=FailingAdapter(), watchdog_s=5.0)
    command = RobotCommand("move", {"distance": 0.2, "direction": "forward"})
    try:
        gateway.submit(command)
        deadline = time.monotonic() + 1.0
        result = gateway.get_action(command.action_id)
        while not result.terminal and time.monotonic() < deadline:
            time.sleep(0.01)
            result = gateway.get_action(command.action_id)
    finally:
        gateway.close()

    assert result.status is ActionStatus.FAILED
    assert result.error == "RuntimeError: bridge disconnected"
