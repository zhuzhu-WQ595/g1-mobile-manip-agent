import json
from pathlib import Path

import pytest

from agent.models import DemoModel, load_model_from_env
from agent.permissions import check_tool_call
from agent.prompts import SYSTEM_PROMPT
from agent.toolkit import TOOL_HANDLERS, TOOL_SCHEMAS
from agent.message_builder import user_message


ROOT = Path(__file__).resolve().parents[1]


def test_agent_root_has_no_legacy_facades():
    legacy_facades = {
        "approvals.py",
        "evaluation.py",
        "goal_runner.py",
        "hooks.py",
        "memory.py",
        "model_adapter.py",
        "plans.py",
        "prompt.py",
        "skills.py",
        "tasks.py",
        "tools.py",
    }

    assert not legacy_facades.intersection(path.name for path in (ROOT / "agent").glob("*.py"))


def test_robot_modules_have_single_canonical_home():
    agent_robot_files = {path.name for path in (ROOT / "agent" / "robot").glob("*.py")}

    assert agent_robot_files == {"__init__.py", "client.py", "policy.py", "tools.py"}
    assert (ROOT / "contracts" / "robot.py").is_file()
    assert (ROOT / "robot_runtime" / "gateway_server.py").is_file()
    assert (ROOT / "robot_runtime" / "adapter.py").is_file()
    assert (ROOT / "robot_runtime" / "safety.py").is_file()
    assert (ROOT / "robot_runtime" / "simulator.py").is_file()


def test_robot_runtime_does_not_depend_on_agent_package():
    for path in (ROOT / "robot_runtime").glob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "from agent" not in source
        assert "import agent" not in source


def test_canonical_package_imports_work():
    from agent.execution import GoalRunner
    from agent.routing import requested_task_action
    from agent.scheduling import ResourceRegistry, ResourceSelector
    from contracts.resource import ExecutionResource
    from contracts.robot import RobotCommand
    from evaluations.runner import EvaluationCase
    from robot_runtime.adapter import RobotRuntimeAdapter
    from robot_runtime.gateway_server import RobotGateway

    assert DemoModel is not None
    assert callable(load_model_from_env)
    assert isinstance(SYSTEM_PROMPT, str)
    assert GoalRunner is not None
    assert callable(requested_task_action)
    assert ExecutionResource is not None
    assert ResourceRegistry is not None
    assert ResourceSelector is not None
    assert RobotCommand is not None
    assert EvaluationCase is not None
    assert RobotGateway is not None
    assert RobotRuntimeAdapter is not None


def test_tool_registry_has_matching_handlers_and_schemas():
    schema_names = {item["function"]["name"] for item in TOOL_SCHEMAS}
    handler_names = set(TOOL_HANDLERS)

    assert handler_names <= schema_names
    assert schema_names - handler_names == {
        "invoke_remote_service",
        "perception_observe",
        "perception_check_path",
    }
    assert "read_file" in handler_names
    assert "count_files_by_extension" in handler_names
    assert "create_plan" in handler_names
    assert "list_skills" in handler_names
    assert "get_recent_tool_events" in handler_names
    assert "request_edit_file" in handler_names
    assert "cancel_pending_action" in handler_names
    assert "list_approval_history" in handler_names
    assert "get_approval_details" in handler_names
    assert "get_task_details" in handler_names
    assert "start_task" in handler_names
    assert "complete_task" in handler_names
    assert "fail_task" in handler_names
    assert "retry_task" in handler_names
    assert "cancel_task" in handler_names
    assert "create_task_plan" in handler_names
    assert "get_task_plan" in handler_names
    assert "validate_task_plan" in handler_names
    assert "run_task_cycle" in handler_names
    assert "edit_file" not in handler_names
    assert "invoke_remote_service" not in handler_names


def test_demo_model_routes_to_tool_call():
    model = DemoModel()
    response = model.complete([user_message("count python files")], tools=[])

    assert response["type"] == "tool_calls"
    assert response["tool_calls"][0]["name"] == "count_files_by_extension"
    assert response["tool_calls"][0]["arguments"] == {"extension": ".py"}


def test_openai_adapter_echoes_reasoning_content_after_tool_call(monkeypatch):
    from agent.message_builder import assistant_tool_call_message, tool_result_message
    from agent.models.openai_compatible import OpenAICompatibleChatModel

    responses = [
        {
            "choices": [
                {
                    "message": {
                        "content": None,
                        "reasoning_content": "reason before tool call",
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "function": {"name": "create_task", "arguments": '{"title":"demo"}'},
                            }
                        ],
                    }
                }
            ]
        },
        {"choices": [{"message": {"content": "任务已创建", "reasoning_content": "summary reasoning"}}]},
    ]
    payloads = []

    class FakeResponse:
        def __init__(self, data):
            self.data = data

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            return json.dumps(self.data).encode("utf-8")

    def fake_urlopen(request, timeout):
        payloads.append(json.loads(request.data.decode("utf-8")))
        return FakeResponse(responses[len(payloads) - 1])

    monkeypatch.setattr("agent.models.openai_compatible.urllib.request.urlopen", fake_urlopen)
    model = OpenAICompatibleChatModel.__new__(OpenAICompatibleChatModel)
    model.model = "deepseek-test"
    model.base_url = "https://example.test"
    model.api_key = "test-key"

    first = model.complete([user_message("创建任务 demo")], [{"type": "function"}], system_prompt="system")
    history = [
        user_message("创建任务 demo"),
        assistant_tool_call_message(first["tool_calls"], first["reasoning_content"]),
        tool_result_message("call_1", "create_task", "Created task_1: demo"),
    ]
    second = model.complete(history, [], system_prompt="summarize")

    assert second["text"] == "任务已创建"
    assert "tools" not in payloads[1]
    assistant_payload = next(message for message in payloads[1]["messages"] if message["role"] == "assistant")
    assert assistant_payload["reasoning_content"] == "reason before tool call"


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


def test_demo_model_routes_task_lifecycle():
    model = DemoModel()

    create = model.complete([user_message("创建任务 检查项目结构 :: 运行测试")], tools=[])
    start = model.complete([user_message("开始任务 task_123")], tools=[])
    fail = model.complete([user_message("fail task_123 :: tests failed")], tools=[])
    retry = model.complete([user_message("重试 task_123")], tools=[])
    complete = model.complete([user_message("完成 task_123 :: 全部通过")], tools=[])
    cancel = model.complete([user_message("cancel task_123 :: obsolete")], tools=[])
    details = model.complete([user_message("查看任务 task_123 详情")], tools=[])

    assert create["tool_calls"][0] == {
        "id": "demo_call_1",
        "name": "create_task",
        "arguments": {"title": "检查项目结构", "detail": "运行测试"},
    }
    assert start["tool_calls"][0]["name"] == "start_task"
    assert fail["tool_calls"][0]["arguments"] == {"task_id": "task_123", "error": "tests failed"}
    assert retry["tool_calls"][0]["name"] == "retry_task"
    assert complete["tool_calls"][0]["arguments"] == {"task_id": "task_123", "result": "全部通过"}
    assert cancel["tool_calls"][0]["arguments"] == {"task_id": "task_123", "reason": "obsolete"}
    assert details["tool_calls"][0]["name"] == "get_task_details"


def test_demo_model_routes_task_aliases():
    model = DemoModel()

    start = model.complete([user_message("开始当前任务")], tools=[])
    complete = model.complete([user_message("完成最新任务 :: 全部通过")], tools=[])
    plan = model.complete([user_message("为当前任务创建计划 :: read README.md; count python files")], tools=[])

    assert start["tool_calls"][0] == {
        "id": "demo_call_1",
        "name": "start_task",
        "arguments": {"task_id": "当前任务"},
    }
    assert complete["tool_calls"][0]["arguments"] == {"task_id": "最新任务", "result": "全部通过"}
    assert plan["tool_calls"][0]["arguments"] == {
        "task_id": "当前任务",
        "steps": ["read README.md", "count python files"],
    }


def test_demo_model_routes_task_plan_linking():
    model = DemoModel()
    create = model.complete(
        [user_message("为任务 task_123 创建计划 :: read README.md; count python files")],
        tools=[],
    )
    show = model.complete([user_message("查看任务 task_123 的计划")], tools=[])
    validate = model.complete([user_message("validate task plan task_123")], tools=[])

    assert create["tool_calls"][0]["name"] == "create_task_plan"
    assert create["tool_calls"][0]["arguments"] == {
        "task_id": "task_123",
        "steps": ["read README.md", "count python files"],
    }
    assert show["tool_calls"][0]["name"] == "get_task_plan"
    assert show["tool_calls"][0]["arguments"] == {"task_id": "task_123"}
    assert validate["tool_calls"][0]["name"] == "validate_task_plan"


def test_recent_tool_events_permission_is_allowed():
    check_tool_call("get_recent_tool_events", {"limit": 3})
    check_tool_call("cancel_pending_action", {"approval_id": "approval_001"})
    check_tool_call("list_approval_history", {"limit": 3})
    check_tool_call("get_approval_details", {"approval_id": "approval_001"})
    check_tool_call("get_task_details", {"task_id": "task_123"})
    check_tool_call("start_task", {"task_id": "task_123"})
    check_tool_call("complete_task", {"task_id": "task_123"})
    check_tool_call("fail_task", {"task_id": "task_123", "error": "failed"})
    check_tool_call("retry_task", {"task_id": "task_123"})
    check_tool_call("cancel_task", {"task_id": "task_123"})
    check_tool_call("create_task_plan", {"task_id": "task_123", "steps": ["read README.md"]})
    check_tool_call("get_task_plan", {"task_id": "task_123"})
    check_tool_call("validate_task_plan", {"task_id": "task_123"})
    check_tool_call("run_task_cycle", {"title": "inspect project"})


def test_edit_approval_permission_stays_inside_workspace():
    check_tool_call("request_edit_file", {"path": "notes/example.txt"})
    with pytest.raises(PermissionError, match="Path is outside workspace"):
        check_tool_call("request_edit_file", {"path": "../outside.txt"})


def test_agent_returns_recent_tool_events_table_directly(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    from agent.agent_loop import Agent
    from agent.models import DemoModel
    from agent.state import event_log

    state_dir = tmp_path / ".agent_state"
    monkeypatch.setattr(event_log, "STATE_DIR", state_dir)
    monkeypatch.setattr(event_log, "HOOK_LOG", state_dir / "tool_events.jsonl")
    event_log.record_tool_event({"tool": "demo", "arguments": {}, "status": "ok", "result": "done"})

    answer = Agent(DemoModel()).run_turn("recent 1 tool events")

    assert answer.startswith("Recent tool events:")
    assert "| # | Time | Tool | Status | Arguments | Result |" in answer
    assert "Tool result:" not in answer


def test_explicit_task_request_executes_only_one_action(tmp_path, monkeypatch):
    from agent.agent_loop import Agent, requested_task_action
    from agent.state import task_store

    class GreedyTaskModel:
        def __init__(self):
            self.calls = 0
            self.tool_counts = []

        def complete(self, messages, tools, system_prompt=None):
            self.calls += 1
            self.tool_counts.append(len(tools))
            if self.calls == 2:
                return {
                    "type": "message",
                    "text": "任务已创建并保持 pending 状态。下一步可以单独开始任务。",
                }
            return {
                "type": "tool_calls",
                "tool_calls": [
                    {"id": "greedy_1", "name": "create_task", "arguments": {"title": "wrong", "detail": ""}},
                    {"id": "greedy_2", "name": "start_task", "arguments": {"task_id": "task_1"}},
                ],
            }

    state_dir = tmp_path / ".agent_state"
    monkeypatch.setattr(task_store, "STATE_DIR", state_dir)
    monkeypatch.setattr(task_store, "TASKS_FILE", state_dir / "tasks.json")

    model = GreedyTaskModel()
    trace = Agent(model).run_turn_with_trace("创建任务 生命周期验证 :: 验证失败、重试和完成")

    assert model.calls == 2
    assert model.tool_counts[0] > 0
    assert model.tool_counts[1] == 0
    assert [event["tool"] for event in trace["events"]] == ["create_task"]
    assert trace["answer"] == "任务已创建并保持 pending 状态。下一步可以单独开始任务。"
    assert task_store._load()[0]["status"] == "pending"
    assert task_store._load()[0]["title"] == "生命周期验证"
    assert requested_task_action("开始任务 <task_123>") == {
        "tool": "start_task",
        "arguments": {"task_id": "task_123"},
    }


def test_task_action_parser_accepts_current_task_aliases():
    from agent.agent_loop import requested_task_action

    assert requested_task_action("开始当前任务") == {
        "tool": "start_task",
        "arguments": {"task_id": "当前任务"},
    }
    assert requested_task_action("完成最新任务 :: 全部通过") == {
        "tool": "complete_task",
        "arguments": {"task_id": "最新任务", "result": "全部通过"},
    }
    assert requested_task_action("标记刚才那个任务失败 :: 测试失败") == {
        "tool": "fail_task",
        "arguments": {"task_id": "刚才那个任务", "error": "测试失败"},
    }
    assert requested_task_action("为当前任务创建计划 :: read README.md; count python files") == {
        "tool": "create_task_plan",
        "arguments": {"task_id": "当前任务", "steps": ["read README.md", "count python files"]},
    }


def test_model_can_generate_task_plan_but_cannot_execute_it_in_same_turn(tmp_path, monkeypatch):
    from agent.agent_loop import Agent
    from agent.planning import store
    from agent.state import task_store

    state_dir = tmp_path / ".agent_state"
    monkeypatch.setattr(store, "STATE_DIR", state_dir)
    monkeypatch.setattr(store, "PLANS_FILE", state_dir / "plans.json")
    monkeypatch.setattr(task_store, "STATE_DIR", state_dir)
    monkeypatch.setattr(task_store, "TASKS_FILE", state_dir / "tasks.json")
    task_id = task_store.create_task("inspect project", "read and count").split(":", 1)[0].removeprefix("Created ")

    class PlanGeneratingModel:
        def __init__(self):
            self.calls = 0
            self.tool_counts = []

        def complete(self, messages, tools, system_prompt=None):
            self.calls += 1
            self.tool_counts.append(len(tools))
            if self.calls == 1:
                return {
                    "type": "tool_calls",
                    "tool_calls": [{"id": "details", "name": "get_task_details", "arguments": {"task_id": task_id}}],
                }
            if self.calls == 2:
                return {
                    "type": "tool_calls",
                    "tool_calls": [
                        {
                            "id": "plan",
                            "name": "create_task_plan",
                            "arguments": {
                                "task_id": task_id,
                                "steps": ["read README.md", "count python files", "summarize results"],
                            },
                        }
                    ],
                }
            return {"type": "message", "text": "计划已生成，尚未执行。"}

    model = PlanGeneratingModel()
    trace = Agent(model).run_turn_with_trace(f"请为任务 {task_id} 自动生成计划")

    assert [event["tool"] for event in trace["events"]] == ["get_task_details", "create_task_plan"]
    assert model.tool_counts[-1] == 0
    assert trace["answer"] == "计划已生成，尚未执行。"
    plan = store.load_plans()[0]
    assert [step["status"] for step in plan["steps"]] == ["pending", "pending", "pending"]
    assert [step["executor"]["mode"] for step in plan["steps"]] == ["tool", "tool", "summary"]


def test_demo_model_routes_complete_task_cycle():
    model = DemoModel()
    response = model.complete(
        [user_message("run task inspect project :: read README.md; count python files; summarize results")],
        tools=[],
    )

    assert response["tool_calls"][0]["name"] == "run_task_cycle"
    assert response["tool_calls"][0]["arguments"] == {
        "title": "inspect project",
        "steps": ["read README.md", "count python files", "summarize results"],
    }


def test_demo_model_routes_natural_language_project_cycle():
    model = DemoModel()
    response = model.complete([user_message("帮我完整检查一下当前项目结构，并总结结果")], tools=[])

    assert response["tool_calls"][0]["name"] == "run_task_cycle"
    assert response["tool_calls"][0]["arguments"] == {
        "title": "检查项目结构",
        "steps": ["workspace summary", "list files in agent", "read README.md", "summarize results"],
    }


def test_agent_returns_task_cycle_report_directly(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "README.md").write_text("cycle readme", encoding="utf-8")

    from agent import permissions
    from agent.agent_loop import Agent
    from agent.planning import store
    from agent.state import task_store

    state_dir = tmp_path / ".agent_state"
    monkeypatch.setattr(permissions, "WORKSPACE_ROOT", tmp_path.resolve())
    monkeypatch.setattr(store, "STATE_DIR", state_dir)
    monkeypatch.setattr(store, "PLANS_FILE", state_dir / "plans.json")
    monkeypatch.setattr(task_store, "STATE_DIR", state_dir)
    monkeypatch.setattr(task_store, "TASKS_FILE", state_dir / "tasks.json")

    answer = Agent(DemoModel()).run_turn("run task inspect project :: read README.md; summarize results")

    assert answer.startswith("Task cycle report")
    assert "Execution trace" in answer
    assert "Plan steps" in answer
    assert "`read_file`" in answer
    assert "Tool result:" not in answer


def test_agent_executes_current_plan_alias(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "README.md").write_text("current plan readme", encoding="utf-8")

    from agent import permissions
    from agent.agent_loop import Agent
    from agent.planning import store
    from agent.planning.actions import create_plan

    state_dir = tmp_path / ".agent_state"
    monkeypatch.setattr(permissions, "WORKSPACE_ROOT", tmp_path.resolve())
    monkeypatch.setattr(store, "STATE_DIR", state_dir)
    monkeypatch.setattr(store, "PLANS_FILE", state_dir / "plans.json")
    create_plan("current alias plan", ["read README.md"])

    trace = Agent(DemoModel()).run_turn_with_trace("execute next step of current plan")

    assert trace["events"][0]["tool"] == "execute_next_plan_step"
    assert trace["events"][0]["arguments"] == {"plan_id": "current plan"}
    assert "Executed step 1" in trace["answer"]
    assert "current plan readme" in trace["answer"]


def test_system_prompt_contains_key_sections():
    assert "Current capabilities:" in SYSTEM_PROMPT
    assert "Robot-control rules:" in SYSTEM_PROMPT
    assert "General rules:" in SYSTEM_PROMPT
    assert "capability registry" in SYSTEM_PROMPT
    assert "authoritative capability set" in SYSTEM_PROMPT
    assert "Do not call tools that are not listed" in SYSTEM_PROMPT
    assert "current, latest, last, recent" in SYSTEM_PROMPT
    assert "run_task_cycle" in SYSTEM_PROMPT
    assert "project-structure inspection" in SYSTEM_PROMPT
    assert "current plan" in SYSTEM_PROMPT
    assert "run pytest" in SYSTEM_PROMPT
    assert "tool <tool_name>" in SYSTEM_PROMPT
