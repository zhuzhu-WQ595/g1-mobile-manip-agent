from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from urllib.parse import urlparse


SERVICE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


@dataclass(frozen=True)
class ServiceEndpoint:
    name: str
    base_url: str
    token: str | None = None

    def __post_init__(self) -> None:
        if not SERVICE_NAME_PATTERN.fullmatch(self.name):
            raise ValueError(f"Invalid remote service name: {self.name}")
        parsed = urlparse(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError(f"Remote service URL must use HTTP or HTTPS: {self.base_url}")


class ServiceRegistry:
    def __init__(self, endpoints: list[ServiceEndpoint] | tuple[ServiceEndpoint, ...]) -> None:
        self._endpoints = {endpoint.name: endpoint for endpoint in endpoints}
        if len(self._endpoints) != len(endpoints):
            raise ValueError("Remote service names must be unique")

    @classmethod
    def from_env(cls) -> ServiceRegistry:
        raw = os.environ.get("REMOTE_SERVICES", "{}").strip() or "{}"
        try:
            configured = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("REMOTE_SERVICES must be a JSON object") from exc
        if not isinstance(configured, dict):
            raise ValueError("REMOTE_SERVICES must be a JSON object")

        endpoints: list[ServiceEndpoint] = []
        for name, value in configured.items():
            token = None
            if isinstance(value, str):
                base_url = value
            elif isinstance(value, dict):
                base_url = str(value.get("url", ""))
                token_env = str(value.get("token_env", "")).strip()
                token = os.environ.get(token_env) if token_env else None
            else:
                raise ValueError(f"Remote service {name} must be a URL or configuration object")
            endpoints.append(ServiceEndpoint(str(name), base_url.rstrip("/"), token))
        return cls(endpoints)

    def resolve(self, name: str) -> ServiceEndpoint:
        try:
            return self._endpoints[name]
        except KeyError as exc:
            available = ", ".join(sorted(self._endpoints)) or "none"
            raise PermissionError(
                f"Remote service is not configured: {name}. Available services: {available}"
            ) from exc

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._endpoints))
