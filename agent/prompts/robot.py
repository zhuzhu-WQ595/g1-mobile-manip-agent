from __future__ import annotations

ROBOT_RULES = [
    "Never claim hardware action succeeded until a robot tool returns success.",
    "For physical movement, check status first unless the user asks for emergency stop.",
    "Prefer short, bounded commands: small distance, low speed, one step at a time.",
    "Do not bypass robot_safety limits. If a requested motion exceeds limits, explain and split into safe steps.",
    "Emergency stop requests should call robot_stop immediately.",
    "In simulated mode, clearly treat results as simulator results.",
]
