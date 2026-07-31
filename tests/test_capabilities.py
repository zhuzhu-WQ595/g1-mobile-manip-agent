from agent.agent_loop import Agent
from agent.capabilities import CAPABILITY_REGISTRY
from agent.toolkit import TOOL_SCHEMAS
from contracts.capability import CapabilityRisk, CapabilityTarget


def _selected_names(text: str) -> set[str]:
    return {spec.tool_name for spec in CAPABILITY_REGISTRY.select(text)}


def test_capability_catalog_covers_every_registered_tool():
    tool_names = {schema["function"]["name"] for schema in TOOL_SCHEMAS}
    capabilities = CAPABILITY_REGISTRY.all()

    assert len(capabilities) == len(tool_names)
    assert {spec.tool_name for spec in capabilities} == tool_names
    assert len({spec.name for spec in capabilities}) == len(capabilities)


def test_capability_metadata_is_structured_and_serializable():
    spec = CAPABILITY_REGISTRY.get("read_file")

    assert spec.domain == "workspace"
    assert spec.execution_target is CapabilityTarget.LOCAL_TOOLKIT
    assert spec.risk_level is CapabilityRisk.READ
    assert spec.input_schema["required"] == ["path"]
    assert spec.to_dict()["execution_target"] == "local_toolkit"


def test_remote_service_capability_uses_remote_target():
    spec = CAPABILITY_REGISTRY.get("invoke_remote_service")

    assert spec.domain == "service"
    assert spec.execution_target is CapabilityTarget.REMOTE_SERVICE
    assert spec.risk_level is CapabilityRisk.EXECUTE
    assert "network" in spec.tags


def test_perception_capabilities_are_read_only_remote_observations():
    for name in ("perception_observe", "perception_check_path"):
        spec = CAPABILITY_REGISTRY.get(name)
        assert spec.domain == "perception"
        assert spec.execution_target is CapabilityTarget.REMOTE_SERVICE
        assert spec.risk_level is CapabilityRisk.READ
        assert "observation" in spec.tags


def test_workspace_read_goal_excludes_unrelated_and_mutating_tools():
    names = _selected_names("read README.md and inspect the workspace")

    assert "read_file" in names
    assert "get_workspace_summary" in names
    assert "write_file" not in names
    assert "robot_move" not in names


def test_workspace_write_goal_includes_read_and_approval_dependencies():
    names = _selected_names("write notes/result.txt and overwrite it only after approval")

    assert "write_file" in names
    assert "read_file" in names
    assert "request_overwrite_file" in names
    assert "approve_pending_action" in names
    assert "robot_move" not in names


def test_robot_motion_goal_includes_feedback_and_stop_capabilities():
    names = _selected_names("让机器人向前移动 0.2 米并确认动作状态")

    assert "robot_move" in names
    assert "robot_get_status" in names
    assert "robot_get_action_status" in names
    assert "robot_stop" in names
    assert "robot_cancel_action" in names
    assert "perception_check_path" in names
    assert "read_file" not in names


def test_unknown_goal_falls_back_to_all_capabilities():
    assert _selected_names("请分析这个开放问题") == {
        schema["function"]["name"] for schema in TOOL_SCHEMAS
    }


def test_remote_service_goal_selects_only_service_capability():
    names = _selected_names("call external service to control external software")

    assert "invoke_remote_service" in names
    assert "read_file" not in names
    assert "robot_move" not in names


def test_agent_passes_only_selected_capabilities_to_model():
    class RecordingModel:
        def __init__(self) -> None:
            self.tool_names: set[str] = set()
            self.system_prompt = ""

        def complete(self, messages, tools, system_prompt=None):
            self.tool_names = {schema["function"]["name"] for schema in tools}
            self.system_prompt = system_prompt or ""
            return {"type": "message", "text": "done"}

    model = RecordingModel()
    answer = Agent(model).run_turn("read README.md")

    assert answer == "done"
    assert "read_file" in model.tool_names
    assert "write_file" not in model.tool_names
    assert "robot_move" not in model.tool_names
    assert "Capabilities selected for this execution:" in model.system_prompt


def test_agent_rejects_tool_outside_selected_capabilities(monkeypatch):
    monkeypatch.setattr("agent.agent_loop.record_tool_event", lambda event: None)

    class WrongToolModel:
        def __init__(self) -> None:
            self.calls = 0

        def complete(self, messages, tools, system_prompt=None):
            self.calls += 1
            if self.calls == 1:
                return {
                    "type": "tool_calls",
                    "tool_calls": [
                        {"id": "wrong", "name": "robot_move", "arguments": {"distance": 0.2}}
                    ],
                }
            return {"type": "message", "text": "The unrelated tool was rejected."}

    trace = Agent(WrongToolModel()).run_turn_with_trace("read README.md")

    assert trace["events"][0]["status"] == "failed"
    assert trace["events"][0]["capability"] == "robot.robot_move"
    assert "Capability was not selected" in trace["events"][0]["result"]
