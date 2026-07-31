from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class CapabilityRisk(str, Enum):
    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"
    CONTROL = "control"
    MOTION = "motion"


class CapabilityTarget(str, Enum):
    LOCAL_TOOLKIT = "local_toolkit"
    AGENT_STATE = "agent_state"
    ROBOT_GATEWAY = "robot_gateway"
    REMOTE_SERVICE = "remote_service"


@dataclass(frozen=True)
class CapabilitySpec:
    """Stable description of one executable Agent capability."""

    name: str
    description: str
    domain: str
    execution_target: CapabilityTarget
    risk_level: CapabilityRisk
    tool_name: str
    input_schema: dict[str, Any] = field(default_factory=dict)
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("capability name cannot be empty")
        if not self.domain.strip():
            raise ValueError("capability domain cannot be empty")
        if not self.tool_name.strip():
            raise ValueError("capability tool_name cannot be empty")

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "domain": self.domain,
            "execution_target": self.execution_target.value,
            "risk_level": self.risk_level.value,
            "tool_name": self.tool_name,
            "input_schema": self.input_schema,
            "tags": list(self.tags),
        }
