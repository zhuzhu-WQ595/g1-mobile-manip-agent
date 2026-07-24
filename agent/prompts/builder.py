from __future__ import annotations

from .base import BASE_PROMPT
from .capabilities import CAPABILITIES
from .planning import PLANNING_RULES
from .robot import ROBOT_RULES
from .safety import SAFETY_RULES
from .style import STYLE_RULES
from .tools import TOOL_RULES


def _section(title: str, items: list[str]) -> str:
    rows = [f"{title}:"]
    rows.extend(f"- {item}" for item in items)
    return "\n".join(rows)


def build_system_prompt() -> str:
    return "\n\n".join(
        [
            BASE_PROMPT,
            _section("Current capabilities", CAPABILITIES),
            _section("Robot-control rules", ROBOT_RULES),
            _section("General rules", [*TOOL_RULES, *SAFETY_RULES, *PLANNING_RULES, *STYLE_RULES]),
        ]
    )


SYSTEM_PROMPT = build_system_prompt()
