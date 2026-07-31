"""Public Agent-side robot integration API.

Execution, safety enforcement, and hardware drivers belong in
``robot_runtime``. Shared wire types belong in ``contracts``.
"""

from .client import (
    HttpRobotAdapter,
    RobotAdapter,
    SocketRobotAdapter,
    get_robot_adapter,
    reset_robot_adapter,
)
from .policy import validate_plan
from .tools import ROBOT_TOOL_HANDLERS, ROBOT_TOOL_SCHEMAS

__all__ = [
    "HttpRobotAdapter",
    "ROBOT_TOOL_HANDLERS",
    "ROBOT_TOOL_SCHEMAS",
    "RobotAdapter",
    "SocketRobotAdapter",
    "get_robot_adapter",
    "reset_robot_adapter",
    "validate_plan",
]
