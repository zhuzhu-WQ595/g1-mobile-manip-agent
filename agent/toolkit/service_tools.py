from __future__ import annotations

from .schema import schema


REMOTE_SERVICE_TOOL_SCHEMAS: list[dict[str, object]] = [
    schema(
        "invoke_remote_service",
        "Invoke an operation on a preconfigured remote service by symbolic service name.",
        {
            "service": {
                "type": "string",
                "description": "Configured service name, never a URL.",
            },
            "operation": {"type": "string"},
            "payload": {"type": "object"},
        },
        ["service", "operation"],
    ),
    schema(
        "perception_observe",
        "Collect a structured observation from the configured perception service.",
        {
            "source": {
                "type": "string",
                "description": "Requested sensor source, such as front_camera or lidar.",
            }
        },
    ),
    schema(
        "perception_check_path",
        "Check whether a requested robot path is clear before motion.",
        {
            "direction": {"type": "string", "enum": ["forward", "backward"]},
            "distance": {"type": "number", "minimum": 0.0},
        },
        ["direction", "distance"],
    ),
]
