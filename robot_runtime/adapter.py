from __future__ import annotations

import os
import threading
from collections.abc import Callable
from typing import Protocol, runtime_checkable

from contracts.robot import RobotCommand, RobotResult, RobotState

MotionFeedback = Callable[[float | None], None]


@runtime_checkable
class RobotRuntimeAdapter(Protocol):
    """Boundary implemented by a simulator, ROS bridge, or hardware driver.

    ``execute_motion`` runs in a gateway worker thread. Implementations must
    observe ``cancel_event``, emit best-effort normalized progress through the
    callback, honor ``RobotCommand.timeout_s``, and return a terminal result.
    """

    @property
    def name(self) -> str: ...

    def get_state(self) -> RobotState: ...

    def execute(self, command: RobotCommand) -> RobotResult: ...

    def execute_motion(
        self,
        command: RobotCommand,
        cancel_event: threading.Event,
        feedback: MotionFeedback,
    ) -> RobotResult: ...

    def emergency_stop(self) -> RobotResult: ...

    def close(self) -> None: ...


def create_runtime_adapter(
    name: str | None = None,
    *,
    sim_time_scale: float | None = None,
) -> RobotRuntimeAdapter:
    selected = (name or os.environ.get("ROBOT_RUNTIME_ADAPTER", "simulated")).strip().lower()
    if selected == "simulated":
        from .simulator import SimulatedRobotAdapter

        return SimulatedRobotAdapter(time_scale=sim_time_scale)
    if selected == "ros2":
        from .ros2_adapter import ROS2RobotAdapter

        return ROS2RobotAdapter()
    if selected == "microduck":
        from .microduck_adapter import MicroDuckAdapter

        return MicroDuckAdapter()
    raise RuntimeError(
        f"Unknown robot runtime adapter: {selected}. Available adapters: simulated, ros2, microduck"
    )
