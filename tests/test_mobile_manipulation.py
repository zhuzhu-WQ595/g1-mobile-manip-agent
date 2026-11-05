from __future__ import annotations

import json

import pytest

from agent.execution import GoalRunner, MOBILE_MANIP_GOAL_TOOLS, MOBILE_MANIP_RULES
from agent.toolkit import mobile_tools
from robot_runtime.isaac_sim import reset_mobile_manip_backend


class ScriptedModel:
    def __init__(self, calls: list[tuple[str, dict]]) -> None:
        self.calls = list(calls)
        self.index = 0

    def complete(self, messages, tools, system_prompt=None):
        if not tools:
            return {"type": "message", "text": "1. navigate 2. open fridge 3. pick apple 4. return"}
        if self.index < len(self.calls):
            name, args = self.calls[self.index]
            self.index += 1
            return {"type": "tool_calls", "tool_calls": [{"id": f"c{self.index}", "name": name, "arguments": args}]}
        return {"type": "message", "text": "mission done"}


@pytest.fixture(autouse=True)
def _mock_backend(monkeypatch):
    monkeypatch.setenv("MOBILE_MANIP_BACKEND", "mock")
    reset_mobile_manip_backend()
    yield
    reset_mobile_manip_backend()


def test_vla_requires_navigation_first():
    result = json.loads(mobile_tools.vla_run_skill("open the fridge door"))
    assert result["ok"] is False
    assert result["error"] == "target_not_reachable"


def test_fetch_apple_and_return_home():
    script = [
        ("nav_go_to_place", {"place": "kitchen"}),
        ("vla_run_skill", {"instruction": "open the fridge door"}),
        ("vla_run_skill", {"instruction": "pick up the apple"}),
        ("nav_go_to_place", {"place": "home"}),
    ]
    result = GoalRunner(
        ScriptedModel(script),
        max_steps=8,
        tool_names=MOBILE_MANIP_GOAL_TOOLS,
        goal_rules=MOBILE_MANIP_RULES,
    ).run("go to the kitchen, get an apple from the fridge and come back")

    assert result["status"] == "completed"
    pose = json.loads(mobile_tools.slam_get_pose())
    assert pose["at_place"] == "home"
    assert pose["holding"] == "apple"
