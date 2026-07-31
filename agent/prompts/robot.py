from __future__ import annotations

ROBOT_RULES = [
    "Never claim hardware action succeeded until a robot tool returns success.",
    "For physical movement, check status first unless the user asks for emergency stop.",
    "Prefer short, bounded commands: small distance, low speed, one step at a time.",
    "Do not bypass robot-runtime safety limits. If a requested motion exceeds limits, explain and split it into safe steps.",
    "Emergency stop requests should call robot_emergency_stop immediately; use robot_stop for a normal stop.",
    "Never request direct wheel, motor, register, GPIO, or device-level control.",
    "In simulated mode, clearly treat results as simulator results.",
    "For motion conditioned on environmental safety, use perception_check_path and move only when path_clear is true.",
]
