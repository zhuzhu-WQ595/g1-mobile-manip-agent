from __future__ import annotations

import json
import math
import os
import threading
import time
from collections.abc import Callable
from pathlib import Path

from contracts.robot import ActionStatus, RobotCommand, RobotResult, RobotState

from .safety import validate_command

STATE_DIR = Path.cwd() / ".agent_state"
STATE_FILE = STATE_DIR / "robot_state.json"


class SimulatedRobotAdapter:
    def __init__(self, time_scale: float | None = None) -> None:
        self.time_scale = (
            float(os.environ.get("ROBOT_SIM_TIME_SCALE", "1"))
            if time_scale is None
            else time_scale
        )
        if self.time_scale <= 0:
            raise ValueError("time_scale must be greater than 0")
        self.state = self._load_state()
        self.actions: dict[str, RobotResult] = {}

    @property
    def name(self) -> str:
        return "simulated"

    def get_state(self) -> RobotState:
        return self.state

    def get_action(self, action_id: str) -> RobotResult:
        result = self.actions.get(action_id)
        if result is not None:
            return result
        return RobotResult(
            False,
            f"action not found: {action_id}",
            self.state,
            action_id=action_id,
            status=ActionStatus.FAILED,
            error="action_not_found",
        )

    def cancel_action(self, action_id: str) -> RobotResult:
        result = self.actions.get(action_id)
        if result is None:
            return self.get_action(action_id)
        if result.terminal:
            return RobotResult(
                False,
                f"action is already {result.status.value}",
                self.state,
                action_id=action_id,
                status=result.status,
                error="action_already_terminal",
            )
        cancelled = RobotResult(
            True,
            "action cancelled",
            self.state,
            action_id=action_id,
            status=ActionStatus.CANCELLED,
        )
        return self._record(cancelled)

    def emergency_stop(self) -> RobotResult:
        self.state.stopped = True
        self.state.emergency_stopped = True
        self.state.last_command = "emergency_stop"
        for action_id, result in list(self.actions.items()):
            if not result.terminal:
                self.actions[action_id] = RobotResult(
                    True,
                    "action cancelled by emergency stop",
                    self._state_snapshot(),
                    action_id=action_id,
                    status=ActionStatus.CANCELLED,
                )
        command = RobotCommand("emergency_stop")
        return self._record(
            RobotResult(
                True,
                "emergency stop latched",
                self.state,
                action_id=command.action_id,
                status=ActionStatus.SUCCEEDED,
            )
        )

    def close(self) -> None:
        return

    def execute(self, command: RobotCommand) -> RobotResult:
        action = command.action
        params = command.params
        self.state.mode = "simulated"
        self.state.last_command = action

        try:
            validate_command(command, self.state)
        except ValueError as exc:
            return self._record(
                RobotResult(
                    False,
                    "action rejected by simulator safety",
                    self.state,
                    action_id=command.action_id,
                    status=ActionStatus.FAILED,
                    error=str(exc),
                )
            )

        if action == "get_status":
            return self._complete(command, "status read")
        if action == "stop":
            self.state.stopped = True
            return self._complete(command, "robot stopped")
        if action == "speak":
            return self._complete(command, f"speak: {params.get('text', '')}")
        if action == "capture_image":
            return self._complete(
                command,
                "simulated camera frame captured",
                {"frame": "simulated://camera/latest"},
            )
        if action == "move":
            distance = float(params.get("distance", 0.0))
            direction = str(params.get("direction", "forward"))
            sign = 1.0 if direction == "forward" else -1.0
            heading = math.radians(self.state.heading_deg or 0.0)
            self.state.x = (self.state.x or 0.0) + math.cos(heading) * distance * sign
            self.state.y = (self.state.y or 0.0) + math.sin(heading) * distance * sign
            self.state.battery_percent = max(0.0, (self.state.battery_percent or 0.0) - distance * 0.2)
            self.state.stopped = True
            return self._complete(command, f"moved {direction} {distance:.2f}m")
        if action == "rotate":
            angle = float(params.get("angle", 0.0))
            self.state.heading_deg = ((self.state.heading_deg or 0.0) + angle) % 360
            self.state.battery_percent = max(0.0, (self.state.battery_percent or 0.0) - abs(angle) * 0.002)
            self.state.stopped = True
            return self._complete(command, f"rotated {angle:.1f}deg")
        if action == "set_wheel_speed":
            left = float(params.get("left", 0.0))
            right = float(params.get("right", 0.0))
            self.state.stopped = left == 0 and right == 0
            return self._complete(command, f"wheel speed set left={left:.2f} right={right:.2f}")
        return self._record(
            RobotResult(
                False,
                f"unsupported simulator action: {action}",
                self.state,
                action_id=command.action_id,
                status=ActionStatus.FAILED,
                error="unsupported_action",
            )
        )

    def execute_motion(
        self,
        command: RobotCommand,
        cancel_event: threading.Event,
        feedback: Callable[[float | None], None],
    ) -> RobotResult:
        """Run a simulated long action while exposing real cancellation points."""
        started = time.monotonic()
        duration = self._estimated_duration(command)
        self.state.stopped = False
        feedback(0.0)

        while True:
            elapsed = time.monotonic() - started
            if cancel_event.is_set():
                self.state.stopped = True
                return RobotResult(
                    True,
                    "action cancelled by runtime",
                    self._state_snapshot(),
                    {"command": command.to_dict()},
                    action_id=command.action_id,
                    status=ActionStatus.CANCELLED,
                    error="runtime_cancelled",
                )
            if elapsed >= command.timeout_s:
                self.state.stopped = True
                return RobotResult(
                    False,
                    "action timed out",
                    self._state_snapshot(),
                    {"command": command.to_dict()},
                    action_id=command.action_id,
                    status=ActionStatus.TIMED_OUT,
                    progress=min(0.99, elapsed / duration),
                    error="action_timeout",
                )
            if elapsed >= duration:
                return self.execute(command)
            feedback(min(0.99, elapsed / duration))
            cancel_event.wait(min(0.05, max(0.01, duration - elapsed)))

    def _estimated_duration(self, command: RobotCommand) -> float:
        speed = max(abs(float(command.params.get("speed", 0.3))), 0.05)
        if command.action == "move":
            raw_duration = abs(float(command.params.get("distance", 0.0))) / speed
        else:
            raw_duration = abs(float(command.params.get("angle", 0.0))) / (speed * 90.0)
        return max(0.2, raw_duration * self.time_scale)

    def _load_state(self) -> RobotState:
        if not STATE_FILE.exists():
            return RobotState()
        try:
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            return RobotState(**{key: data[key] for key in RobotState().__dict__ if key in data})
        except (OSError, json.JSONDecodeError, TypeError):
            return RobotState()

    def _complete(self, command: RobotCommand, message: str, data: dict | None = None) -> RobotResult:
        result_data = {"command": command.to_dict(), **(data or {})}
        return self._record(
            RobotResult(
                True,
                message,
                self.state,
                result_data,
                action_id=command.action_id,
                status=ActionStatus.SUCCEEDED,
                progress=1.0,
            )
        )

    def _record(self, result: RobotResult) -> RobotResult:
        if result.state is self.state:
            result.state = self._state_snapshot()
        if result.action_id:
            self.actions[result.action_id] = result
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(self.state.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return result

    def _state_snapshot(self) -> RobotState:
        return RobotState.from_dict(self.state.to_dict(), mode=self.state.mode)
