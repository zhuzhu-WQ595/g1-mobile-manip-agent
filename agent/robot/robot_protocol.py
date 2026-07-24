from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class RobotState:
    mode: str = "simulated"
    battery_percent: float = 85.0
    x: float = 0.0
    y: float = 0.0
    heading_deg: float = 0.0
    front_obstacle_m: float = 1.5
    stopped: bool = True
    last_command: str = "none"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RobotCommand:
    action: str
    params: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"action": self.action, "params": self.params}


@dataclass
class RobotResult:
    ok: bool
    message: str
    state: RobotState | None = None
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"ok": self.ok, "message": self.message, "data": self.data}
        if self.state is not None:
            payload["state"] = self.state.to_dict()
        return payload


def result_text(result: RobotResult) -> str:
    status = "ok" if result.ok else "error"
    text = f"{status}: {result.message}"
    if result.state is not None:
        state = result.state
        text += (
            f"\nstate: mode={state.mode}, battery={state.battery_percent:.1f}%, "
            f"pose=({state.x:.2f}, {state.y:.2f}, {state.heading_deg:.1f}deg), "
            f"front_obstacle={state.front_obstacle_m:.2f}m, stopped={state.stopped}"
        )
    return text