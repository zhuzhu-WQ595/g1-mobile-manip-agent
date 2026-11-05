from __future__ import annotations

import argparse
import json
import os
import urllib.request
from typing import Any

from contracts.execution import ExecutionError, ExecutionRequest, ExecutionStatus
from contracts.observation import Observation

from .demo_server import ExecutionServiceHTTPServer


class SimulatedPerceptionService:
    """Perception service that checks real robot lidar data via Gateway."""

    def __init__(self, scene: str = "clear") -> None:
        if scene not in {"clear", "blocked", "failure"}:
            raise ValueError("scene must be clear, blocked, or failure")
        self.scene = scene
        self._gateway_url = os.environ.get("ROBOT_BASE_URL", "http://127.0.0.1:9000").rstrip("/")

    def _get_robot_state(self) -> dict[str, Any] | None:
        try:
            req = urllib.request.Request(
                f"{self._gateway_url}/robot/state",
                headers={"Content-Type": "application/json"},
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
            return data.get("state", data)
        except Exception:
            return None

    def execute(self, request: ExecutionRequest) -> dict[str, Any]:
        operation = str(request.arguments.get("operation", "")).strip()
        payload = request.arguments.get("payload", {})
        if operation not in {"observe", "check_path"}:
            return request.event(
                ExecutionStatus.FAILED,
                error=ExecutionError(
                    "unsupported_operation",
                    f"unsupported perception operation: {operation}",
                ),
            ).to_dict()
        if not isinstance(payload, dict):
            return request.event(
                ExecutionStatus.FAILED,
                error=ExecutionError("invalid_payload", "payload must be an object"),
            ).to_dict()
        if self.scene == "failure":
            return request.event(
                ExecutionStatus.FAILED,
                error=ExecutionError("sensor_unavailable", "simulated perception sensor unavailable", True),
            ).to_dict()

        if self.scene == "blocked":
            obstacles: tuple[dict[str, Any], ...] = (
                {"label": "wall", "distance_m": 0.12, "bearing_deg": 0.0},
            )
            observation = Observation(
                source=str(payload.get("source", "front_sensor")),
                path_clear=False,
                objects=obstacles,
                obstacles=obstacles,
                confidence=0.98,
                metadata={"scene": self.scene, "operation": operation},
            )
            observation_data = observation.to_dict()
            return request.event(
                ExecutionStatus.SUCCEEDED,
                result=observation_data,
                observation=observation_data,
            ).to_dict()

        # scene == "clear": check real robot lidar data
        robot_state = self._get_robot_state()
        front_obstacle = None
        if robot_state is not None:
            front_obstacle = robot_state.get("front_obstacle_m")

        requested_distance = float(payload.get("distance", 1.0))
        path_clear = True
        obstacles_list: list[dict[str, Any]] = []

        if front_obstacle is not None:
            if front_obstacle < requested_distance + 0.3:
                path_clear = False
                obstacles_list.append({
                    "label": "obstacle",
                    "distance_m": round(front_obstacle, 3),
                    "bearing_deg": 0.0,
                })
        else:
            path_clear = False
            obstacles_list.append({
                "label": "unknown",
                "distance_m": 0.0,
                "bearing_deg": 0.0,
            })

        observation = Observation(
            source=str(payload.get("source", "front_sensor")),
            path_clear=path_clear,
            objects=tuple(obstacles_list),
            obstacles=tuple(obstacles_list),
            confidence=0.95 if front_obstacle is not None else 0.3,
            metadata={
                "scene": self.scene,
                "operation": operation,
                "requested_path": {
                    "direction": payload.get("direction"),
                    "distance": payload.get("distance"),
                },
                "front_obstacle_m": front_obstacle,
            },
        )
        observation_data = observation.to_dict()
        return request.event(
            ExecutionStatus.SUCCEEDED,
            result=observation_data,
            observation=observation_data,
        ).to_dict()


class PerceptionServiceHTTPServer(ExecutionServiceHTTPServer):
    def __init__(
        self,
        server_address: tuple[str, int],
        service: SimulatedPerceptionService | None = None,
    ) -> None:
        super().__init__(
            server_address,
            service or SimulatedPerceptionService(),
            "self-test-perception",
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the simulated perception service")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9030)
    parser.add_argument("--scene", choices=["clear", "blocked", "failure"], default="clear")
    args = parser.parse_args()
    server = PerceptionServiceHTTPServer(
        (args.host, args.port),
        SimulatedPerceptionService(args.scene),
    )
    print(
        f"Perception service listening on http://{args.host}:{args.port} "
        f"with scene={args.scene}"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
