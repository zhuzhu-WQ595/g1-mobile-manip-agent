from __future__ import annotations

import argparse
from typing import Any

from contracts.execution import ExecutionError, ExecutionRequest, ExecutionStatus
from contracts.observation import Observation

from .demo_server import ExecutionServiceHTTPServer


class SimulatedPerceptionService:
    """Deterministic perception boundary for feedback-loop development."""

    def __init__(self, scene: str = "clear") -> None:
        if scene not in {"clear", "blocked", "failure"}:
            raise ValueError("scene must be clear, blocked, or failure")
        self.scene = scene

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

        blocked = self.scene == "blocked"
        obstacles: tuple[dict[str, Any], ...] = (
            ({"label": "box", "distance_m": 0.12, "bearing_deg": 0.0},)
            if blocked
            else ()
        )
        observation = Observation(
            source=str(payload.get("source", "front_sensor")),
            path_clear=not blocked,
            objects=obstacles,
            obstacles=obstacles,
            confidence=0.98,
            metadata={
                "scene": self.scene,
                "operation": operation,
                "requested_path": {
                    "direction": payload.get("direction"),
                    "distance": payload.get("distance"),
                },
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
