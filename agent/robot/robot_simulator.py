from __future__ import annotations

import json
import math
from pathlib import Path

from .robot_protocol import RobotCommand, RobotResult, RobotState

STATE_DIR = Path.cwd() / ".agent_state"
STATE_FILE = STATE_DIR / "robot_state.json"


class SimulatedRobotAdapter:
    def __init__(self) -> None:
        self.state = self._load_state()

    def get_state(self) -> RobotState:
        return self.state

    def execute(self, command: RobotCommand) -> RobotResult:
        action = command.action
        params = command.params
        self.state.mode = "simulated"
        self.state.last_command = action

        if action == "get_status":
            return self._save(RobotResult(True, "status read", self.state))
        if action == "stop":
            self.state.stopped = True
            return self._save(RobotResult(True, "robot stopped", self.state))
        if action == "speak":
            return self._save(RobotResult(True, f"speak: {params.get('text', '')}", self.state))
        if action == "capture_image":
            return self._save(RobotResult(True, "simulated camera frame captured", self.state, {"frame": "simulated://camera/latest"}))
        if action == "move":
            distance = float(params.get("distance", 0.0))
            direction = str(params.get("direction", "forward"))
            sign = 1.0 if direction == "forward" else -1.0
            heading = math.radians(self.state.heading_deg)
            self.state.x += math.cos(heading) * distance * sign
            self.state.y += math.sin(heading) * distance * sign
            self.state.battery_percent = max(0.0, self.state.battery_percent - distance * 0.2)
            self.state.stopped = False
            return self._save(RobotResult(True, f"moved {direction} {distance:.2f}m", self.state))
        if action == "rotate":
            angle = float(params.get("angle", 0.0))
            self.state.heading_deg = (self.state.heading_deg + angle) % 360
            self.state.battery_percent = max(0.0, self.state.battery_percent - abs(angle) * 0.002)
            self.state.stopped = False
            return self._save(RobotResult(True, f"rotated {angle:.1f}deg", self.state))
        if action == "set_wheel_speed":
            left = float(params.get("left", 0.0))
            right = float(params.get("right", 0.0))
            self.state.stopped = left == 0 and right == 0
            return self._save(RobotResult(True, f"wheel speed set left={left:.2f} right={right:.2f}", self.state))
        return RobotResult(False, f"unsupported simulator action: {action}", self.state)

    def _load_state(self) -> RobotState:
        if not STATE_FILE.exists():
            return RobotState()
        try:
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            return RobotState(**{key: data[key] for key in RobotState().__dict__ if key in data})
        except (OSError, json.JSONDecodeError, TypeError):
            return RobotState()

    def _save(self, result: RobotResult) -> RobotResult:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(self.state.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return result