"""Stable data contracts shared across runtime boundaries."""

from .capability import CapabilityRisk, CapabilitySpec, CapabilityTarget
from .execution import (
    ExecutionError,
    ExecutionEvent,
    ExecutionRequest,
    ExecutionResult,
    ExecutionStatus,
    normalize_execution_status,
)
from .observation import Observation
from .robot import ActionStatus, RobotCommand, RobotResult, RobotState

__all__ = [
    "ActionStatus",
    "CapabilityRisk",
    "CapabilitySpec",
    "CapabilityTarget",
    "ExecutionError",
    "ExecutionEvent",
    "ExecutionRequest",
    "ExecutionResult",
    "ExecutionStatus",
    "normalize_execution_status",
    "Observation",
    "RobotCommand",
    "RobotResult",
    "RobotState",
]
