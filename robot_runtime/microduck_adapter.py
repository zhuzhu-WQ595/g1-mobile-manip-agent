"""MicroDuck MuJoCo adapter — bridges the self-test agent framework to the
microduck_rl HTTP bridge running inside infer_policy.py.

This adapter implements the RobotRuntimeAdapter protocol so the existing
RobotGateway can drive the MicroDuck simulation. It translates high-level
RobotCommand actions (move, rotate, stop, get_status, plus microduck-specific
actions like sit, kick, roulade, ground_pick) into HTTP calls to the bridge.
"""

from __future__ import annotations

import json
import math
import os
import threading
import time
import urllib.request
from typing import Any

from contracts.robot import ActionStatus, RobotCommand, RobotResult, RobotState


class MicroDuckAdapter:
    """Adapter that talks to the microduck_bridge HTTP server.

    Unlike the simulated adapter, this one proxies to a live MuJoCo sim.
    State is read from the bridge's /robot/state endpoint. Actions are sent
    as HTTP POSTs and return immediately (the sim applies them next tick).
    """

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = (
            base_url
            or os.environ.get("MICRODUCK_BRIDGE_URL", "http://127.0.0.1:9001")
        ).rstrip("/")
        self.timeout = float(os.environ.get("MICRODUCK_TIMEOUT", "5"))
        self._state_cache: RobotState = RobotState(mode="microduck")
        self._actions: dict[str, RobotResult] = {}

    @property
    def name(self) -> str:
        return "microduck"

    def get_state(self) -> RobotState:
        try:
            data = self._request("/robot/state", method="GET")
            state_data = data.get("state", data)
            if isinstance(state_data, dict):
                self._state_cache = RobotState.from_dict(state_data, mode="microduck")
        except Exception:
            pass
        return self._state_cache

    def execute(self, command: RobotCommand) -> RobotResult:
        action = command.action
        params = command.params

        if action == "get_status":
            state = self.get_state()
            return RobotResult(
                True,
                "status read",
                state,
                {"command": command.to_dict()},
                action_id=command.action_id,
                status=ActionStatus.SUCCEEDED,
                progress=1.0,
            )

        if action == "stop":
            return self._post_bridge("/robot/stop", {}, command)

        if action == "move":
            distance = float(params.get("distance", 0.0))
            direction = str(params.get("direction", "forward"))
            speed = float(params.get("speed", 0.2))
            vx = speed if direction == "forward" else -speed
            return self._post_bridge(
                "/robot/walk",
                {"vx": vx, "vy": 0.0, "vtheta": 0.0},
                command,
            )

        if action == "walk":
            vx = float(params.get("vx", 0.0))
            vy = float(params.get("vy", 0.0))
            vtheta = float(params.get("vtheta", 0.0))
            return self._post_bridge(
                "/robot/walk",
                {"vx": vx, "vy": vy, "vtheta": vtheta},
                command,
            )

        if action == "rotate":
            angle_deg = float(params.get("angle", 0.0))
            speed = float(params.get("speed", 0.3))
            vtheta = math.radians(angle_deg) * (speed / 0.3)
            return self._post_bridge(
                "/robot/walk",
                {"vx": 0.0, "vy": 0.0, "vtheta": vtheta},
                command,
            )

        if action == "sit":
            return self._post_bridge("/robot/sit", {}, command)

        if action == "kick":
            foot = str(params.get("foot", "left"))
            return self._post_bridge("/robot/kick", {"foot": foot}, command)

        if action == "roulade":
            return self._post_bridge("/robot/roulade", {}, command)

        if action == "ground_pick":
            return self._post_bridge("/robot/ground_pick", {}, command)

        if action == "head":
            return self._post_bridge(
                "/robot/head",
                {
                    "neck_pitch": float(params.get("neck_pitch", 0.0)),
                    "head_pitch": float(params.get("head_pitch", 0.0)),
                    "head_yaw": float(params.get("head_yaw", 0.0)),
                    "head_roll": float(params.get("head_roll", 0.0)),
                },
                command,
            )

        if action == "body_pose":
            return self._post_bridge(
                "/robot/body_pose",
                {
                    "z": float(params.get("z", 0.0)),
                    "pitch": float(params.get("pitch", 0.0)),
                    "roll": float(params.get("roll", 0.0)),
                },
                command,
            )

        if action == "emergency_stop":
            return self._post_bridge("/robot/emergency_stop", {}, command)

        if action == "speak":
            return RobotResult(
                True,
                f"speak: {params.get('text', '')}",
                self.get_state(),
                {"command": command.to_dict()},
                action_id=command.action_id,
                status=ActionStatus.SUCCEEDED,
                progress=1.0,
            )

        if action == "capture_image":
            return RobotResult(
                True,
                "microduck camera not available",
                self.get_state(),
                {"command": command.to_dict(), "frame": "microduck://camera/unavailable"},
                action_id=command.action_id,
                status=ActionStatus.SUCCEEDED,
                progress=1.0,
            )

        return RobotResult(
            False,
            f"unsupported microduck action: {action}",
            self.get_state(),
            {"command": command.to_dict()},
            action_id=command.action_id,
            status=ActionStatus.FAILED,
            error="unsupported_action",
        )

    def execute_motion(
        self,
        command: RobotCommand,
        cancel_event: threading.Event,
        feedback,
    ) -> RobotResult:
        """For move/rotate, send the command and wait for the estimated duration."""
        result = self.execute(command)
        if not result.ok:
            return result

        params = command.params
        if command.action == "move":
            speed = max(abs(float(params.get("speed", 0.2))), 0.05)
            distance = abs(float(params.get("distance", 0.0)))
            duration = distance / speed
        elif command.action == "rotate":
            speed = max(abs(float(params.get("speed", 0.3))), 0.05)
            angle = abs(float(params.get("angle", 0.0)))
            duration = angle / (speed * 90.0)
        else:
            duration = 1.0

        duration = max(0.2, duration)
        started = time.monotonic()
        while True:
            elapsed = time.monotonic() - started
            if cancel_event.is_set():
                self.execute(RobotCommand("stop"))
                return RobotResult(
                    True,
                    "action cancelled",
                    self.get_state(),
                    {"command": command.to_dict()},
                    action_id=command.action_id,
                    status=ActionStatus.CANCELLED,
                    error="cancelled_by_request",
                )
            if elapsed >= duration:
                self.execute(RobotCommand("stop"))
                return RobotResult(
                    True,
                    f"completed {command.action}",
                    self.get_state(),
                    {"command": command.to_dict()},
                    action_id=command.action_id,
                    status=ActionStatus.SUCCEEDED,
                    progress=1.0,
                )
            feedback(min(0.99, elapsed / duration))
            cancel_event.wait(min(0.05, duration - elapsed))

    def emergency_stop(self) -> RobotResult:
        command = RobotCommand("emergency_stop")
        return self._post_bridge("/robot/emergency_stop", {}, command)

    def close(self) -> None:
        return

    def _post_bridge(
        self, path: str, payload: dict[str, Any], command: RobotCommand
    ) -> RobotResult:
        try:
            data = self._request(path, payload, method="POST")
            ok = data.get("ok", True)
            message = data.get("message", "ok")
            state = self.get_state()
            result = RobotResult(
                ok,
                message,
                state,
                {"command": command.to_dict()},
                action_id=command.action_id,
                status=ActionStatus.SUCCEEDED if ok else ActionStatus.FAILED,
                progress=1.0,
                error=data.get("error") if not ok else None,
            )
            self._actions[command.action_id] = result
            return result
        except Exception as exc:
            state = self.get_state()
            result = RobotResult(
                False,
                f"bridge request failed: {exc}",
                state,
                {"command": command.to_dict()},
                action_id=command.action_id,
                status=ActionStatus.FAILED,
                error=f"{type(exc).__name__}: {exc}",
            )
            self._actions[command.action_id] = result
            return result

    def _request(
        self,
        path: str,
        payload: dict[str, Any] | None = None,
        method: str = "POST",
    ) -> dict[str, Any]:
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=body,
            headers={"Content-Type": "application/json"},
            method=method,
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("bridge response must be a JSON object")
        return data
