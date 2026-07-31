from __future__ import annotations

import json
import urllib.request
from dataclasses import replace
from typing import Any

from contracts.capability import CapabilitySpec
from contracts.execution import ExecutionEvent, ExecutionRequest
from services.registry import ServiceRegistry


MAX_RESPONSE_BYTES = 1024 * 1024

REMOTE_CAPABILITY_BINDINGS = {
    "perception_observe": ("perception", "observe"),
    "perception_check_path": ("perception", "check_path"),
}


class HttpRemoteServiceExecutor:
    """Send the shared execution contract to an allowed HTTP service."""

    def __init__(self, registry: ServiceRegistry | None = None) -> None:
        self.registry = registry

    def __call__(
        self,
        request: ExecutionRequest,
        capability: CapabilitySpec,
    ) -> ExecutionEvent:
        binding = REMOTE_CAPABILITY_BINDINGS.get(capability.tool_name)
        if binding is None:
            outbound_request = request
        else:
            service_name, operation = binding
            outbound_request = replace(
                request,
                arguments={
                    "service": service_name,
                    "operation": operation,
                    "payload": request.arguments,
                },
            )

        service_name = str(outbound_request.arguments.get("service", "")).strip()
        operation = str(outbound_request.arguments.get("operation", "")).strip()
        payload = outbound_request.arguments.get("payload", {})
        if not service_name:
            raise ValueError("remote service name cannot be empty")
        if not operation:
            raise ValueError("remote service operation cannot be empty")
        if not isinstance(payload, dict):
            raise ValueError("remote service payload must be an object")

        registry = self.registry or ServiceRegistry.from_env()
        endpoint = registry.resolve(service_name)
        body = json.dumps(outbound_request.to_dict(), ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if endpoint.token:
            headers["Authorization"] = f"Bearer {endpoint.token}"
        http_request = urllib.request.Request(
            f"{endpoint.base_url}/executions",
            data=body,
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(http_request, timeout=request.timeout_s) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ValueError("remote service response exceeds 1 MiB")
        try:
            data: Any = json.loads(raw.decode("utf-8", errors="strict"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("remote service returned invalid JSON") from exc
        if not isinstance(data, dict):
            raise ValueError("remote service response must be a JSON object")

        event = ExecutionEvent.from_dict(data)
        if event.execution_id != request.execution_id:
            raise ValueError("remote service response execution_id does not match request")
        if event.capability != capability.name:
            raise ValueError("remote service response capability does not match request")
        if event.execution_target != request.execution_target:
            raise ValueError("remote service response target does not match request")
        return event
