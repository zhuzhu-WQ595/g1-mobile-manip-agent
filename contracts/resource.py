from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ResourceStatus(str, Enum):
    AVAILABLE = "available"
    DEGRADED = "degraded"
    BUSY = "busy"
    OFFLINE = "offline"


@dataclass(frozen=True)
class ExecutionResource:
    """One concrete runtime resource capable of executing Agent capabilities."""

    resource_id: str
    execution_target: str
    capabilities: frozenset[str]
    status: ResourceStatus = ResourceStatus.AVAILABLE
    priority: int = 0
    load: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.resource_id.strip():
            raise ValueError("resource_id cannot be empty")
        if not self.execution_target.strip():
            raise ValueError("resource execution_target cannot be empty")
        if not self.capabilities:
            raise ValueError("resource capabilities cannot be empty")
        if not 0.0 <= self.load <= 1.0:
            raise ValueError("resource load must be between 0 and 1")
        object.__setattr__(self, "capabilities", frozenset(self.capabilities))

    def supports(self, capability: str, execution_target: str) -> bool:
        return capability in self.capabilities and execution_target == self.execution_target

    def to_dict(self) -> dict[str, Any]:
        return {
            "resource_id": self.resource_id,
            "execution_target": self.execution_target,
            "capabilities": sorted(self.capabilities),
            "status": self.status.value,
            "priority": self.priority,
            "load": self.load,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExecutionResource:
        capabilities = data.get("capabilities", [])
        metadata = data.get("metadata", {})
        if not isinstance(capabilities, (list, tuple, set, frozenset)):
            raise ValueError("resource capabilities must be a collection")
        return cls(
            resource_id=str(data.get("resource_id", "")),
            execution_target=str(data.get("execution_target", "")),
            capabilities=frozenset(str(item) for item in capabilities),
            status=ResourceStatus(str(data.get("status", ResourceStatus.AVAILABLE.value))),
            priority=int(data.get("priority", 0)),
            load=float(data.get("load", 0.0)),
            metadata=metadata if isinstance(metadata, dict) else {},
        )
