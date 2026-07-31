from __future__ import annotations

import json
import os
import socket
import urllib.request
from abc import ABC, abstractmethod
from typing import Any

from contracts.robot import RobotCommand, RobotResult, RobotState
from robot_runtime.simulator import SimulatedRobotAdapter


class RobotAdapter(ABC):
    @abstractmethod
    def get_state(self) -> RobotState:
        ...

    @abstractmethod
    def execute(self, command: RobotCommand) -> RobotResult:
        ...

    @abstractmethod
    def get_action(self, action_id: str) -> RobotResult:
        ...

    @abstractmethod
    def cancel_action(self, action_id: str) -> RobotResult:
        ...

    @abstractmethod
    def emergency_stop(self) -> RobotResult:
        ...


class SocketRobotAdapter(RobotAdapter):
    def __init__(self, host: str | None = None, port: int | None = None) -> None:
        self.host = host or os.environ.get("ROBOT_HOST", "127.0.0.1")
        self.port = int(port or os.environ.get("ROBOT_PORT", "9000"))
        self.timeout = float(os.environ.get("ROBOT_TIMEOUT", "3"))

    def get_state(self) -> RobotState:
        data = self._exchange("get_state")
        state_data = data.get("state", data)
        if not isinstance(state_data, dict):
            raise ValueError("Socket gateway response does not contain robot state")
        return RobotState.from_dict(state_data, mode="socket")

    def execute(self, command: RobotCommand) -> RobotResult:
        data = self._exchange("submit_action", {"command": command.to_dict()})
        return RobotResult.from_dict(data, mode="socket", action_id=command.action_id)

    def get_action(self, action_id: str) -> RobotResult:
        data = self._exchange("get_action", {"action_id": action_id})
        return RobotResult.from_dict(data, mode="socket", action_id=action_id)

    def cancel_action(self, action_id: str) -> RobotResult:
        data = self._exchange("cancel_action", {"action_id": action_id})
        return RobotResult.from_dict(data, mode="socket", action_id=action_id)

    def emergency_stop(self) -> RobotResult:
        data = self._exchange("emergency_stop")
        return RobotResult.from_dict(data, mode="socket")

    def _exchange(self, operation: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        request = {"operation": operation, **(payload or {})}
        with socket.create_connection((self.host, self.port), timeout=self.timeout) as sock:
            sock.sendall((json.dumps(request) + "\n").encode("utf-8"))
            raw = sock.recv(8192).decode("utf-8", errors="replace").strip()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("Socket gateway returned invalid JSON") from exc
        if not isinstance(data, dict):
            raise ValueError("Socket gateway response must be a JSON object")
        return data


class HttpRobotAdapter(RobotAdapter):
    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = (base_url or os.environ.get("ROBOT_BASE_URL", "http://127.0.0.1:9000")).rstrip("/")
        self.timeout = float(os.environ.get("ROBOT_TIMEOUT", "5"))

    def get_state(self) -> RobotState:
        data = self._request("/robot/state", method="GET")
        state_data = data.get("state", data)
        if not isinstance(state_data, dict):
            raise ValueError("HTTP gateway response does not contain robot state")
        return RobotState.from_dict(state_data, mode="http")

    def execute(self, command: RobotCommand) -> RobotResult:
        data = self._request("/robot/actions", command.to_dict())
        return RobotResult.from_dict(data, mode="http", action_id=command.action_id)

    def get_action(self, action_id: str) -> RobotResult:
        data = self._request(f"/robot/actions/{action_id}", method="GET")
        return RobotResult.from_dict(data, mode="http", action_id=action_id)

    def cancel_action(self, action_id: str) -> RobotResult:
        data = self._request(f"/robot/actions/{action_id}/cancel", {})
        return RobotResult.from_dict(data, mode="http", action_id=action_id)

    def emergency_stop(self) -> RobotResult:
        data = self._request("/robot/emergency-stop", {})
        return RobotResult.from_dict(data, mode="http")

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
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("HTTP gateway returned invalid JSON") from exc
        if not isinstance(data, dict):
            raise ValueError("HTTP gateway response must be a JSON object")
        return data


_ADAPTER: RobotAdapter | None = None


def get_robot_adapter() -> RobotAdapter:
    global _ADAPTER
    if _ADAPTER is not None:
        return _ADAPTER

    mode = os.environ.get("ROBOT_MODE", "simulated").strip().lower()
    if mode == "socket":
        _ADAPTER = SocketRobotAdapter()
    elif mode == "http":
        _ADAPTER = HttpRobotAdapter()
    else:
        _ADAPTER = SimulatedRobotAdapter()
    return _ADAPTER


def reset_robot_adapter() -> None:
    global _ADAPTER
    _ADAPTER = None
