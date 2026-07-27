import pytest

from agent.model_adapter import DemoModel, load_model_from_env
from agent.permissions import check_tool_call
from agent.prompt import SYSTEM_PROMPT
from agent.tools import TOOL_HANDLERS, TOOL_SCHEMAS
from agent.message_builder import user_message


def test_compat_imports_work():
    assert DemoModel is not None
    assert callable(load_model_from_env)
    assert isinstance(SYSTEM_PROMPT, str)


def test_tool_registry_has_matching_handlers_and_schemas():
    schema_names = {item["function"]["name"] for item in TOOL_SCHEMAS}
    handler_names = set(TOOL_HANDLERS)

    assert schema_names == handler_names
    assert "read_file" in handler_names
    assert "count_files_by_extension" in handler_names
    assert "create_plan" in handler_names
    assert "list_skills" in handler_names
    assert "get_recent_tool_events" in handler_names
    assert "request_edit_file" in handler_names
    assert "cancel_pending_action" in handler_names
    assert "list_approval_history" in handler_names
    assert "get_approval_details" in handler_names
    assert "edit_file" not in handler_names


def test_demo_model_routes_to_tool_call():
    model = DemoModel()
    response = model.complete([user_message("count python files")], tools=[])

    assert response["type"] == "tool_calls"
    assert response["tool_calls"][0]["name"] == "count_files_by_extension"
    assert response["tool_calls"][0]["arguments"] == {"extension": ".py"}


def test_demo_model_routes_tool_events_to_log_tool():
    model = DemoModel()
    response = model.complete([user_message("recent 3 tool events")], tools=[])

    assert response["type"] == "tool_calls"
    assert response["tool_calls"][0]["name"] == "get_recent_tool_events"
    assert response["tool_calls"][0]["arguments"] == {"limit": 3}


def test_demo_model_routes_edit_to_approval():
    model = DemoModel()
    response = model.complete([user_message("edit notes/test.txt :: hello => hello world")], tools=[])

    assert response["type"] == "tool_calls"
    assert response["tool_calls"][0]["name"] == "request_edit_file"
    assert response["tool_calls"][0]["arguments"] == {
        "path": "notes/test.txt",
        "old_text": "hello",
        "new_text": "hello world",
    }


def test_demo_model_routes_cancel_approval():
    model = DemoModel()
    response = model.complete([user_message("cancel approval_001")], tools=[])

    assert response["type"] == "tool_calls"
    assert response["tool_calls"][0]["name"] == "cancel_pending_action"
    assert response["tool_calls"][0]["arguments"] == {"approval_id": "approval_001"}


def test_demo_model_routes_approval_queries():
    model = DemoModel()
    history = model.complete([user_message("recent 3 approvals")], tools=[])
    details = model.complete([user_message("approval approval_001")], tools=[])

    assert history["tool_calls"][0]["name"] == "list_approval_history"
    assert history["tool_calls"][0]["arguments"] == {"limit": 3}
    assert details["tool_calls"][0]["name"] == "get_approval_details"
    assert details["tool_calls"][0]["arguments"] == {"approval_id": "approval_001"}


def test_recent_tool_events_permission_is_allowed():
    check_tool_call("get_recent_tool_events", {"limit": 3})
    check_tool_call("cancel_pending_action", {"approval_id": "approval_001"})
    check_tool_call("list_approval_history", {"limit": 3})
    check_tool_call("get_approval_details", {"approval_id": "approval_001"})


def test_edit_approval_permission_stays_inside_workspace():
    check_tool_call("request_edit_file", {"path": "notes/example.txt"})
    with pytest.raises(PermissionError, match="Path is outside workspace"):
        check_tool_call("request_edit_file", {"path": "../outside.txt"})


def test_agent_returns_recent_tool_events_table_directly(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    from agent.agent_loop import Agent
    from agent.model_adapter import DemoModel
    from agent.state import event_log

    state_dir = tmp_path / ".agent_state"
    monkeypatch.setattr(event_log, "STATE_DIR", state_dir)
    monkeypatch.setattr(event_log, "HOOK_LOG", state_dir / "tool_events.jsonl")
    event_log.record_tool_event({"tool": "demo", "arguments": {}, "status": "ok", "result": "done"})

    answer = Agent(DemoModel()).run_turn("recent 1 tool events")

    assert answer.startswith("Recent tool events:")
    assert "| # | Time | Tool | Status | Arguments | Result |" in answer
    assert "Tool result:" not in answer


def test_system_prompt_contains_key_sections():
    assert "Current capabilities:" in SYSTEM_PROMPT
    assert "Robot-control rules:" in SYSTEM_PROMPT
    assert "General rules:" in SYSTEM_PROMPT
    assert "create_plan" in SYSTEM_PROMPT
    assert "get_recent_tool_events" in SYSTEM_PROMPT
    assert "request_edit_file" in SYSTEM_PROMPT
    assert "cancel_pending_action" in SYSTEM_PROMPT
    assert "list_approval_history" in SYSTEM_PROMPT
    assert "get_approval_details" in SYSTEM_PROMPT
