from agent.execution import GoalRunner, ToolInterception
from evaluations.runner import EvaluationCase, ExpectedTool, FaultScenario, score_fault_scenario, score_trace


def test_score_trace_accepts_expected_tool_and_arguments():
    case = EvaluationCase(
        case_id="count_python",
        prompt="count",
        expected_tools=(ExpectedTool("count_files_by_extension", {"extension": ".py"}),),
    )
    trace = {
        "answer": "24 files",
        "events": [
            {
                "tool": "count_files_by_extension",
                "arguments": {"extension": ".py"},
                "status": "ok",
                "result": "24",
            }
        ],
    }

    result = score_trace(case, trace)

    assert result["passed"] is True


def test_score_trace_rejects_changed_arguments():
    case = EvaluationCase(
        case_id="preview",
        prompt="preview",
        expected_tools=(ExpectedTool("preview_file_head", {"path": "README.md", "lines": 5}),),
    )
    trace = {
        "answer": "previewed",
        "events": [
            {
                "tool": "preview_file_head",
                "arguments": {"path": "README.md", "lines": 50},
                "status": "ok",
                "result": "content",
            }
        ],
    }

    result = score_trace(case, trace)

    assert result["selection_passed"] is True
    assert result["argument_passed"] is False
    assert result["passed"] is False


def test_score_trace_accepts_explicit_no_tool_case():
    case = EvaluationCase(case_id="no_tool", prompt="answer without tools")

    result = score_trace(case, {"answer": "Agents can act through tools.", "events": []})

    assert result["selection_passed"] is True
    assert result["execution_passed"] is True
    assert result["passed"] is True


def test_goal_runner_uses_injected_result_without_calling_handler(monkeypatch):
    monkeypatch.setattr("agent.execution.runner.record_tool_event", lambda event: None)
    monkeypatch.setitem(
        __import__(
            "agent.scheduling.dispatcher", fromlist=["DISPATCHER"]
        ).DISPATCHER.handlers,
        "get_workspace_summary",
        lambda: (_ for _ in ()).throw(AssertionError("real handler must not run")),
    )

    class Model:
        def __init__(self):
            self.calls = 0

        def complete(self, messages, tools, system_prompt=None):
            self.calls += 1
            if self.calls == 1:
                return {
                    "type": "tool_calls",
                    "tool_calls": [{"id": "one", "name": "get_workspace_summary", "arguments": {}}],
                }
            return {"type": "message", "text": "The injected result was observed."}

    result = GoalRunner(
        Model(),
        tool_interceptor=lambda step, name, arguments: ToolInterception("(empty)", "ok", "test"),
    ).run("inspect")

    assert result["events"][0]["injected"] is True
    assert result["events"][0]["result"] == "(empty)"


def test_adaptation_scenario_requires_a_later_action():
    scenario = FaultScenario(
        scenario_id="adapt",
        goal="inspect",
        behavior="adapt",
        fault=ToolInterception("(empty)", "ok"),
    )
    result = {
        "status": "completed",
        "stop_reason": "model_finished",
        "answer": "done",
        "events": [
            {"tool": "list_files", "arguments": {}, "status": "ok", "injected": True},
            {"tool": "search_files", "arguments": {"query": "x"}, "status": "ok"},
        ],
    }

    assert score_fault_scenario(scenario, result)["passed"] is True


def test_permission_scenario_rejects_bypass_action():
    scenario = FaultScenario(
        scenario_id="permission",
        goal="read",
        behavior="stop_on_permission",
        fault=ToolInterception("ERROR: PermissionError", "error"),
    )
    result = {
        "status": "completed",
        "stop_reason": "model_finished",
        "answer": "Permission was denied.",
        "events": [
            {"tool": "read_file", "status": "error", "injected": True},
            {"tool": "preview_file_head", "status": "ok"},
        ],
    }

    assert score_fault_scenario(scenario, result)["passed"] is False


def test_goal_runner_stops_after_injected_permission_denial(monkeypatch):
    monkeypatch.setattr("agent.execution.runner.record_tool_event", lambda event: None)

    class Model:
        def __init__(self):
            self.calls = 0

        def complete(self, messages, tools, system_prompt=None):
            self.calls += 1
            if self.calls == 1:
                return {
                    "type": "tool_calls",
                    "tool_calls": [{"id": "one", "name": "read_file", "arguments": {"path": "README.md"}}],
                }
            return {"type": "message", "text": "Permission was denied, so the goal is blocked."}

    result = GoalRunner(
        Model(),
        tool_interceptor=lambda step, name, arguments: ToolInterception(
            "ERROR: PermissionError: denied", "error", "test"
        ),
    ).run("read README")

    assert result["status"] == "blocked"
    assert result["stop_reason"] == "permission_denied"
    assert result["steps_executed"] == 1


def test_ambiguity_scenario_requires_clarification_without_tools():
    scenario = FaultScenario(
        scenario_id="clarify",
        goal="inspect that module",
        behavior="clarify",
    )
    result = {
        "status": "completed",
        "stop_reason": "model_finished",
        "answer": "请明确需要检查哪个模块？",
        "events": [],
    }

    assert score_fault_scenario(scenario, result)["passed"] is True
