from __future__ import annotations

import json
import os
import socket
import urllib.request
from abc import ABC, abstractmethod
from typing import Any

from .robot_protocol import RobotCommand, RobotResult, RobotState
from .robot_simulator import SimulatedRobotAdapter


class RobotAdapter(ABC):
    @abstractmethod
    def get_state(self) -> RobotState:
        ...

    @abstractmethod
    def execute(self, command: RobotCommand) -> RobotResult:
        ...


class SocketRobotAdapter(RobotAdapter):
    def __init__(self, host: str | None = None, port: int | None = None) -> None:
        self.host = host or os.environ.get("ROBOT_HOST", "127.0.0.1")
        self.port = int(port or os.environ.get("ROBOT_PORT", "9000"))
        self.timeout = float(os.environ.get("ROBOT_TIMEOUT", "3"))

    def get_state(self) -> RobotState:
        result = self.execute(RobotCommand("get_status"))
        if result.state is not None:
            return result.state
        return RobotState(mode="socket", last_command="get_status")

    def execute(self, command: RobotCommand) -> RobotResult:
        payload = command.to_dict()
        with socket.create_connection((self.host, self.port), timeout=self.timeout) as sock:
            sock.sendall((json.dumps(payload) + "\n").encode("utf-8"))
            raw = sock.recv(8192).decode("utf-8", errors="replace").strip()
        return RobotResult(ok=True, message=raw or "socket command sent", state=RobotState(mode="socket", last_command=command.action))


class HttpRobotAdapter(RobotAdapter):
    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = (base_url or os.environ.get("ROBOT_BASE_URL", "http://127.0.0.1:9000")).rstrip("/")
        self.timeout = float(os.environ.get("ROBOT_TIMEOUT", "5"))

    def get_state(self) -> RobotState:
        result = self.execute(RobotCommand("get_status"))
        if result.state is not None:
            return result.state
        return RobotState(mode="http", last_command="get_status")

    def execute(self, command: RobotCommand) -> RobotResult:
        body = json.dumps(command.to_dict()).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/robot/command",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
        try:
            data: dict[str, Any] = json.loads(raw)
        except json.JSONDecodeError:
            data = {"message": raw}
        state = RobotState(mode="http", last_command=command.action)
        return RobotResult(ok=bool(data.get("ok", True)), message=str(data.get("message", "http command sent")), state=state, data=data)


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