from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any
from uuid import uuid4

from .execution import ExecutionError, ExecutionEvent, ExecutionRequest, ExecutionStatus


class ActionStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


TERMINAL_STATUSES = {
    ActionStatus.SUCCEEDED,
    ActionStatus.FAILED,
    ActionStatus.CANCELLED,
    ActionStatus.TIMED_OUT,
}


@dataclass
class RobotState:
    """Robot observation using meters and a ROS-compatible planar heading.

    ``x`` and ``y`` are meters in the runtime's world/map frame. ``heading_deg``
    is zero along +x and increases counterclockwise. Adapters must convert native
    device coordinates into this convention before returning state.
    """

    mode: str = "simulated"
    battery_percent: float | None = 85.0
    x: float | None = 0.0
    y: float | None = 0.0
    heading_deg: float | None = 0.0
    front_obstacle_m: float | None = 1.5
    stopped: bool | None = True
    emergency_stopped: bool | None = False
    last_command: str = "none"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any], mode: str = "unknown") -> RobotState:
        def optional_float(name: str) -> float | None:
            value = data.get(name)
            return None if value is None else float(value)

        def optional_bool(name: str) -> bool | None:
            value = data.get(name)
            if value is None:
                return None
            if not isinstance(value, bool):
                raise ValueError(f"{name} must be a boolean")
            return value

        return cls(
            mode=str(data.get("mode", mode)),
            battery_percent=optional_float("battery_percent"),
            x=optional_float("x"),
            y=optional_float("y"),
            heading_deg=optional_float("heading_deg"),
            front_obstacle_m=optional_float("front_obstacle_m"),
            stopped=optional_bool("stopped"),
            emergency_stopped=optional_bool("emergency_stopped"),
            last_command=str(data.get("last_command", "unknown")),
        )


@dataclass
class RobotCommand:
    """High-level command using SI units, except rotation angles in degrees."""

    action: str
    params: dict[str, Any] = field(default_factory=dict)
    action_id: str = field(default_factory=lambda: f"action_{uuid4().hex}")
    timeout_s: float = 30.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "action": self.action,
            "params": self.params,
            "timeout_s": self.timeout_s,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RobotCommand:
        action = str(data.get("action", "")).strip()
        if not action:
            raise ValueError("action is required")
        params = data.get("params", {})
        if not isinstance(params, dict):
            raise ValueError("params must be an object")
        timeout_s = float(data.get("timeout_s", 30.0))
        if timeout_s <= 0:
            raise ValueError("timeout_s must be greater than 0")
        action_id = str(data.get("action_id", "")).strip()
        if action_id:
            return cls(action=action, params=params, action_id=action_id, timeout_s=timeout_s)
        return cls(action=action, params=params, timeout_s=timeout_s)


@dataclass
class RobotResult:
    ok: bool
    message: str
    state: RobotState | None = None
    data: dict[str, Any] = field(default_factory=dict)
    action_id: str = ""
    status: ActionStatus = ActionStatus.SUCCEEDED
    progress: float | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "action_id": self.action_id,
            "status": self.status.value,
            "ok": self.ok,
            "message": self.message,
            "progress": self.progress,
            "error": self.error,
            "data": self.data,
        }
        if self.state is not None:
            payload["state"] = self.state.to_dict()
        return payload

    def to_execution_event(self, capability: str) -> ExecutionEvent:
        status_map = {
            ActionStatus.PENDING: ExecutionStatus.ACCEPTED,
            ActionStatus.RUNNING: ExecutionStatus.RUNNING,
            ActionStatus.SUCCEEDED: ExecutionStatus.SUCCEEDED,
            ActionStatus.FAILED: ExecutionStatus.FAILED,
            ActionStatus.CANCELLED: ExecutionStatus.CANCELLED,
            ActionStatus.TIMED_OUT: ExecutionStatus.TIMED_OUT,
        }
        command = self.data.get("command", {})
        arguments = command.get("params", {}) if isinstance(command, dict) else {}
        request_kwargs: dict[str, Any] = {}
        if self.action_id:
            request_kwargs["execution_id"] = self.action_id
        request = ExecutionRequest(
            capability=capability,
            execution_target="robot_gateway",
            arguments=arguments if isinstance(arguments, dict) else {},
            metadata={"robot_action_id": self.action_id} if self.action_id else {},
            **request_kwargs,
        )
        execution_status = status_map[self.status]
        error = None
        if execution_status in {
            ExecutionStatus.FAILED,
            ExecutionStatus.CANCELLED,
            ExecutionStatus.TIMED_OUT,
        }:
            error = ExecutionError(
                code=self.error or f"robot_{execution_status.value}",
                message=self.message,
                retryable=execution_status in {ExecutionStatus.FAILED, ExecutionStatus.TIMED_OUT},
            )
        return request.event(
            execution_status,
            progress=self.progress,
            result={"ok": self.ok, "message": self.message, "data": self.data},
            error=error,
            observation=self.state.to_dict() if self.state is not None else None,
        )

    @property
    def terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES

    @classmethod
    def from_dict(cls, data: dict[str, Any], mode: str = "unknown", action_id: str = "") -> RobotResult:
        ok = bool(data.get("ok", True))
        raw_status = str(data.get("status", "succeeded" if ok else "failed"))
        try:
            status = ActionStatus(raw_status)
        except ValueError as exc:
            raise ValueError(f"Unknown robot action status: {raw_status}") from exc

        state_data = data.get("state")
        state = RobotState.from_dict(state_data, mode) if isinstance(state_data, dict) else None
        payload_data = data.get("data", {})
        return cls(
            ok=ok,
            message=str(data.get("message", "robot gateway response")),
            state=state,
            data=payload_data if isinstance(payload_data, dict) else {"value": payload_data},
            action_id=str(data.get("action_id", action_id)),
            status=status,
            progress=float(data["progress"]) if data.get("progress") is not None else None,
            error=str(data["error"]) if data.get("error") is not None else None,
        )


def result_text(result: RobotResult) -> str:
    status = "ok" if result.ok else "error"
    text = f"{status}: {result.message}"
    if result.action_id:
        text += f"\naction: id={result.action_id}, status={result.status.value}"
        if result.progress is not None:
            text += f", progress={result.progress:.0%}"
    if result.error:
        text += f"\nerror: {result.error}"
    if result.state is not None:
        state = result.state
        battery = "unknown" if state.battery_percent is None else f"{state.battery_percent:.1f}%"
        pose = (
            "unknown"
            if state.x is None or state.y is None or state.heading_deg is None
            else f"({state.x:.2f}, {state.y:.2f}, {state.heading_deg:.1f}deg)"
        )
        obstacle = "unknown" if state.front_obstacle_m is None else f"{state.front_obstacle_m:.2f}m"
        stopped = "unknown" if state.stopped is None else str(state.stopped)
        emergency_stopped = "unknown" if state.emergency_stopped is None else str(state.emergency_stopped)
        text += (
            f"\nstate: mode={state.mode}, battery={battery}, pose={pose}, "
            f"front_obstacle={obstacle}, stopped={stopped}, "
            f"emergency_stopped={emergency_stopped}"
        )
    return text
