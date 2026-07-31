from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import unquote, urlparse

from contracts.robot import ActionStatus, RobotCommand, RobotResult, RobotState

from .adapter import RobotRuntimeAdapter, create_runtime_adapter
from .safety import validate_command


class RobotGateway:
    """Thread-safe asynchronous gateway around a runtime adapter."""

    MOTION_ACTIONS = {"move", "rotate"}

    def __init__(
        self,
        adapter: RobotRuntimeAdapter | None = None,
        watchdog_s: float = 15.0,
    ) -> None:
        if watchdog_s <= 0:
            raise ValueError("watchdog_s must be greater than 0")
        self.adapter = adapter or create_runtime_adapter()
        self.watchdog_s = watchdog_s
        self._lock = threading.RLock()
        self._actions: dict[str, RobotResult] = {}
        self._commands: dict[str, RobotCommand] = {}
        self._cancel_events: dict[str, threading.Event] = {}
        self._action_threads: dict[str, threading.Thread] = {}
        self._last_contact = time.monotonic()
        self._closed = threading.Event()
        self._watchdog_thread = threading.Thread(
            target=self._watchdog_loop,
            name="robot-gateway-watchdog",
            daemon=True,
        )
        self._watchdog_thread.start()

    def touch(self) -> None:
        with self._lock:
            self._last_contact = time.monotonic()

    def get_state(self) -> RobotState:
        self.touch()
        with self._lock:
            return self._state_snapshot()

    def submit(self, command: RobotCommand) -> RobotResult:
        self.touch()
        with self._lock:
            existing = self._actions.get(command.action_id)
            if existing is not None:
                return existing

            if command.action == "set_wheel_speed":
                return self._store_failure(command, "Direct wheel-speed control is not exposed by the gateway")
            try:
                validate_command(command, self.adapter.get_state())
            except ValueError as exc:
                return self._store_failure(command, "Action rejected by gateway safety", str(exc))

            if command.action in self.MOTION_ACTIONS and self._active_motion_id() is not None:
                return self._store_failure(command, "Robot is busy with another motion", "robot_busy")

            self._commands[command.action_id] = command
            if command.action in self.MOTION_ACTIONS:
                pending = RobotResult(
                    True,
                    "action accepted",
                    self._state_snapshot(),
                    {"command": command.to_dict()},
                    action_id=command.action_id,
                    status=ActionStatus.PENDING,
                    progress=0.0,
                )
                self._actions[command.action_id] = pending
                cancel_event = threading.Event()
                self._cancel_events[command.action_id] = cancel_event
                thread = threading.Thread(
                    target=self._run_motion,
                    args=(command, cancel_event),
                    name=f"robot-action-{command.action_id}",
                    daemon=True,
                )
                self._action_threads[command.action_id] = thread
                thread.start()
                return pending

            if command.action == "stop":
                self._cancel_active_locked("action cancelled by stop", "normal_stop")
            result = self.adapter.execute(command)
            self._actions[command.action_id] = result
            return result

    def get_action(self, action_id: str) -> RobotResult:
        self.touch()
        with self._lock:
            result = self._actions.get(action_id)
            if result is not None:
                return result
            return RobotResult(
                False,
                f"action not found: {action_id}",
                self._state_snapshot(),
                action_id=action_id,
                status=ActionStatus.FAILED,
                error="action_not_found",
            )

    def cancel_action(self, action_id: str) -> RobotResult:
        self.touch()
        with self._lock:
            current = self._actions.get(action_id)
            if current is None:
                return self.get_action(action_id)
            if current.terminal:
                return RobotResult(
                    False,
                    f"action is already {current.status.value}",
                    self._state_snapshot(),
                    current.data,
                    action_id=action_id,
                    status=current.status,
                    progress=current.progress,
                    error="action_already_terminal",
                )
            cancel_event = self._cancel_events.get(action_id)
            if cancel_event is not None:
                cancel_event.set()
            result = self._cancelled_result(action_id, "action cancelled", "cancelled_by_request")
            self._actions[action_id] = result
            self.adapter.execute(RobotCommand("stop"))
            return result

    def emergency_stop(self) -> RobotResult:
        self.touch()
        with self._lock:
            self._cancel_active_locked("action cancelled by emergency stop", "emergency_stop")
            result = self.adapter.emergency_stop()
            self._actions[result.action_id] = result
            return result

    def close(self) -> None:
        with self._lock:
            if self._closed.is_set():
                return
            self._closed.set()
            self._cancel_active_locked("action cancelled by gateway shutdown", "gateway_shutdown")
            action_threads = list(self._action_threads.values())
        try:
            self.adapter.execute(RobotCommand("stop"))
        finally:
            for thread in action_threads:
                if thread is not threading.current_thread():
                    thread.join(timeout=1.0)
            self.adapter.close()

    def _run_motion(self, command: RobotCommand, cancel_event: threading.Event) -> None:
        with self._lock:
            if self._actions[command.action_id].terminal:
                return
            self._actions[command.action_id] = RobotResult(
                True,
                "action running",
                self._state_snapshot(),
                {"command": command.to_dict()},
                action_id=command.action_id,
                status=ActionStatus.RUNNING,
                progress=0.0,
            )

        def update_progress(progress: float | None) -> None:
            with self._lock:
                current = self._actions[command.action_id]
                if current.terminal:
                    return
                self._actions[command.action_id] = RobotResult(
                    True,
                    "action running",
                    self._state_snapshot(),
                    {"command": command.to_dict()},
                    action_id=command.action_id,
                    status=ActionStatus.RUNNING,
                    progress=progress,
                )

        try:
            result = self.adapter.execute_motion(command, cancel_event, update_progress)
        except Exception as exc:
            result = RobotResult(
                False,
                "runtime adapter failed while executing motion",
                self._state_snapshot(),
                {"command": command.to_dict()},
                action_id=command.action_id,
                status=ActionStatus.FAILED,
                error=f"{type(exc).__name__}: {exc}",
            )
        with self._lock:
            if not self._actions[command.action_id].terminal:
                self._actions[command.action_id] = result
            self._action_threads.pop(command.action_id, None)

    def _watchdog_loop(self) -> None:
        interval = min(0.25, max(0.05, self.watchdog_s / 4))
        while not self._closed.wait(interval):
            with self._lock:
                if time.monotonic() - self._last_contact < self.watchdog_s:
                    continue
                if self._active_motion_id() is None:
                    continue
                self._cancel_active_locked("action cancelled by gateway watchdog", "watchdog_timeout")
                self.adapter.execute(RobotCommand("stop"))

    def _cancel_active_locked(self, message: str, error: str) -> None:
        for action_id, result in list(self._actions.items()):
            if result.status not in {ActionStatus.PENDING, ActionStatus.RUNNING}:
                continue
            cancel_event = self._cancel_events.get(action_id)
            if cancel_event is not None:
                cancel_event.set()
            self._actions[action_id] = self._cancelled_result(action_id, message, error)

    def _cancelled_result(self, action_id: str, message: str, error: str) -> RobotResult:
        command = self._commands.get(action_id)
        data = {"command": command.to_dict()} if command is not None else {}
        return RobotResult(
            True,
            message,
            self._state_snapshot(),
            data,
            action_id=action_id,
            status=ActionStatus.CANCELLED,
            error=error,
        )

    def _store_failure(self, command: RobotCommand, message: str, error: str | None = None) -> RobotResult:
        result = RobotResult(
            False,
            message,
            self._state_snapshot(),
            {"command": command.to_dict()},
            action_id=command.action_id,
            status=ActionStatus.FAILED,
            error=error,
        )
        self._commands[command.action_id] = command
        self._actions[command.action_id] = result
        return result

    def _active_motion_id(self) -> str | None:
        for action_id, result in self._actions.items():
            command = self._commands.get(action_id)
            if (
                command is not None
                and command.action in self.MOTION_ACTIONS
                and result.status in {ActionStatus.PENDING, ActionStatus.RUNNING}
            ):
                return action_id
        return None

    def _state_snapshot(self) -> RobotState:
        state = self.adapter.get_state()
        return RobotState.from_dict(state.to_dict(), mode=state.mode)


class RobotGatewayHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], gateway: RobotGateway) -> None:
        self.gateway = gateway
        super().__init__(address, RobotGatewayRequestHandler)


class RobotGatewayRequestHandler(BaseHTTPRequestHandler):
    server: RobotGatewayHTTPServer

    def do_GET(self) -> None:
        try:
            parts = self._path_parts()
            if parts == ["health"]:
                self._send_json(
                    {
                        "ok": True,
                        "service": "robot-gateway",
                        "adapter": self.server.gateway.adapter.name,
                    }
                )
                return
            if parts == ["robot", "state"]:
                self._send_json({"state": self.server.gateway.get_state().to_dict()})
                return
            if len(parts) == 3 and parts[:2] == ["robot", "actions"]:
                self._send_json(self.server.gateway.get_action(parts[2]).to_dict())
                return
            self._send_json({"ok": False, "error": "route_not_found"}, status=404)
        except Exception as exc:
            self._send_error(exc)

    def do_POST(self) -> None:
        try:
            parts = self._path_parts()
            if parts == ["robot", "actions"]:
                command = RobotCommand.from_dict(self._read_json())
                self._send_json(self.server.gateway.submit(command).to_dict(), status=202)
                return
            if len(parts) == 4 and parts[:2] == ["robot", "actions"] and parts[3] == "cancel":
                self._read_json()
                self._send_json(self.server.gateway.cancel_action(parts[2]).to_dict())
                return
            if parts == ["robot", "emergency-stop"]:
                self._read_json()
                self._send_json(self.server.gateway.emergency_stop().to_dict())
                return
            self._send_json({"ok": False, "error": "route_not_found"}, status=404)
        except ValueError as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=400)
        except Exception as exc:
            self._send_error(exc)

    def _path_parts(self) -> list[str]:
        path = urlparse(self.path).path
        return [unquote(part) for part in path.split("/") if part]

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length > 1_048_576:
            raise ValueError("request body is too large")
        if length == 0:
            return {}
        value = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("request body must be a JSON object")
        return value

    def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_error(self, exc: Exception) -> None:
        self._send_json(
            {"ok": False, "error": f"{type(exc).__name__}: {exc}"},
            status=500,
        )

    def log_message(self, format: str, *args: Any) -> None:
        print(f"gateway: {self.address_string()} - {format % args}")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Run the asynchronous robot runtime gateway.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=int(os.environ.get("ROBOT_PORT", "9000")))
    parser.add_argument(
        "--watchdog-seconds",
        type=float,
        default=float(os.environ.get("ROBOT_GATEWAY_WATCHDOG_S", "15")),
    )
    parser.add_argument(
        "--time-scale",
        type=float,
        default=float(os.environ.get("ROBOT_SIM_TIME_SCALE", "1")),
    )
    parser.add_argument(
        "--adapter",
        default=os.environ.get("ROBOT_RUNTIME_ADAPTER", "simulated"),
        help="Runtime adapter name. Currently available: simulated.",
    )
    args = parser.parse_args()
    if args.host not in {"127.0.0.1", "localhost", "::1"}:
        parser.error("The development gateway only binds to a loopback host")

    gateway = RobotGateway(
        adapter=create_runtime_adapter(args.adapter, sim_time_scale=args.time_scale),
        watchdog_s=args.watchdog_seconds,
    )
    server = RobotGatewayHTTPServer((args.host, args.port), gateway)
    print(
        f"robot gateway: http://{args.host}:{server.server_port} "
        f"(adapter={gateway.adapter.name})"
    )
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping gateway")
    finally:
        gateway.close()
        server.server_close()


if __name__ == "__main__":
    main()
