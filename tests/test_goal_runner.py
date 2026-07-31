import json

from agent.execution import GoalRunner, RobotFeedbackVerifier
from agent.execution.runner import (
    _can_repeat_status_poll,
    _looks_like_tool_request,
)
from agent.models.base import latest_tool_text


def test_goal_runner_uses_feedback_before_next_action(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "README.md").write_text("# demo\nfeedback-driven agent", encoding="utf-8")

    from agent import permissions

    monkeypatch.setattr(permissions, "WORKSPACE_ROOT", tmp_path.resolve())
    monkeypatch.setattr("agent.execution.runner.record_tool_event", lambda event: None)

    class FeedbackModel:
        def __init__(self):
            self.calls = 0

        def complete(self, messages, tools, system_prompt=None):
            self.calls += 1
            if self.calls == 1:
                return {
                    "type": "tool_calls",
                    "tool_calls": [{"id": "one", "name": "get_workspace_summary", "arguments": {}}],
                }
            if self.calls == 2:
                assert "Workspace:" in (latest_tool_text(messages) or "")
                return {
                    "type": "tool_calls",
                    "tool_calls": [{"id": "two", "name": "read_file", "arguments": {"path": "README.md"}}],
                }
            assert "feedback-driven agent" in (latest_tool_text(messages) or "")
            return {"type": "message", "text": "The goal is supported by two observations."}

    result = GoalRunner(FeedbackModel(), max_steps=4).run("verify the project")

    assert result["status"] == "completed"
    assert result["stop_reason"] == "model_finished"
    assert [event["tool"] for event in result["events"]] == ["get_workspace_summary", "read_file"]
    assert result["steps_executed"] == 2


def test_goal_runner_executes_only_first_proposed_tool(monkeypatch):
    monkeypatch.setattr("agent.execution.runner.record_tool_event", lambda event: None)

    class ParallelModel:
        def __init__(self):
            self.calls = 0

        def complete(self, messages, tools, system_prompt=None):
            self.calls += 1
            if self.calls == 1:
                return {
                    "type": "tool_calls",
                    "tool_calls": [
                        {"id": "one", "name": "get_workspace_summary", "arguments": {}},
                        {"id": "two", "name": "count_files_by_extension", "arguments": {"extension": ".py"}},
                    ],
                }
            return {"type": "message", "text": "I inspected the first result before stopping."}

    result = GoalRunner(ParallelModel(), max_steps=3).run("inspect safely")

    assert [event["tool"] for event in result["events"]] == ["get_workspace_summary"]
    assert result["events"][0]["proposed_tool_calls"] == 2


def test_goal_runner_stops_repeated_action(monkeypatch):
    monkeypatch.setattr("agent.execution.runner.record_tool_event", lambda event: None)

    class RepeatingModel:
        def __init__(self):
            self.calls = 0

        def complete(self, messages, tools, system_prompt=None):
            self.calls += 1
            if self.calls <= 2:
                return {
                    "type": "tool_calls",
                    "tool_calls": [{"id": f"call_{self.calls}", "name": "get_workspace_summary", "arguments": {}}],
                }
            return {"type": "message", "text": "The repeated action was stopped."}

    result = GoalRunner(RepeatingModel(), max_steps=4).run("avoid loops")

    assert result["status"] == "blocked"
    assert result["stop_reason"] == "repeated_action"
    assert result["steps_executed"] == 1


def test_goal_runner_recognizes_unexecuted_tool_markup():
    assert _looks_like_tool_request('<｜｜DSML｜｜tool_calls><invoke name="read_file">') is True
    assert _looks_like_tool_request("The available evidence supports the goal.") is False


def test_running_robot_action_allows_repeated_status_poll():
    arguments = {"action_id": "action_1"}
    running_event = {
        "tool": "robot_get_action_status",
        "arguments": arguments,
        "result": json.dumps({"action_id": "action_1", "status": "running", "ok": True}),
    }
    completed_event = {
        **running_event,
        "result": json.dumps({"action_id": "action_1", "status": "succeeded", "ok": True}),
    }

    assert _can_repeat_status_poll("robot_get_action_status", arguments, [running_event]) is True
    assert _can_repeat_status_poll("robot_get_action_status", arguments, [completed_event]) is False
    assert _can_repeat_status_poll("get_workspace_summary", {}, [running_event]) is False


def test_robot_goal_requires_structured_terminal_feedback(monkeypatch):
    monkeypatch.setenv("ROBOT_MODE", "simulated")
    monkeypatch.setattr("agent.execution.runner.record_tool_event", lambda event: None)
    feedback = {
        "action_id": "action_move",
        "status": "succeeded",
        "ok": True,
        "message": "moved forward 0.2m",
        "progress": 1.0,
        "state": {"stopped": True, "emergency_stopped": False, "x": 0.2},
        "data": {},
    }
    handlers = __import__(
        "agent.scheduling.dispatcher", fromlist=["DISPATCHER"]
    ).DISPATCHER.handlers
    monkeypatch.setitem(handlers, "robot_move", lambda **arguments: json.dumps(feedback))

    class RobotModel:
        def __init__(self):
            self.calls = 0

        def complete(self, messages, tools, system_prompt=None):
            self.calls += 1
            if self.calls == 1:
                return {
                    "type": "tool_calls",
                    "tool_calls": [
                        {
                            "id": "move",
                            "name": "robot_move",
                            "arguments": {"distance": 0.2, "direction": "forward", "speed": 0.2},
                        }
                    ],
                }
            return {"type": "message", "text": "The robot moved 0.2m."}

    result = GoalRunner(
        RobotModel(),
        max_steps=3,
        tool_names={"robot_move"},
        completion_verifier=RobotFeedbackVerifier(),
    ).run("move forward 0.2m")

    assert result["status"] == "completed"
    assert result["stop_reason"] == "feedback_verified"
    assert result["verifications"][-1]["achieved"] is True


def test_robot_goal_queries_running_action_before_completion(monkeypatch):
    monkeypatch.setenv("ROBOT_MODE", "simulated")
    monkeypatch.setattr("agent.execution.runner.record_tool_event", lambda event: None)
    handlers = __import__(
        "agent.scheduling.dispatcher", fromlist=["DISPATCHER"]
    ).DISPATCHER.handlers
    monkeypatch.setitem(
        handlers,
        "robot_move",
        lambda **arguments: json.dumps(
            {
                "action_id": "action_running",
                "status": "running",
                "ok": True,
                "message": "motion accepted",
                "progress": 0.4,
                "state": {"stopped": False},
                "data": {},
            }
        ),
    )
    status_calls = {"count": 0}

    def status_handler(**arguments):
        status_calls["count"] += 1
        running = status_calls["count"] == 1
        return json.dumps(
            {
                "action_id": "action_running",
                "status": "running" if running else "succeeded",
                "ok": True,
                "message": "motion running" if running else "motion complete",
                "progress": 0.7 if running else 1.0,
                "state": {"stopped": not running, "x": 0.1 if running else 0.2},
                "data": {},
            }
        )

    monkeypatch.setitem(handlers, "robot_get_action_status", status_handler)

    class AsyncRobotModel:
        def __init__(self):
            self.calls = 0

        def complete(self, messages, tools, system_prompt=None):
            self.calls += 1
            if self.calls == 1:
                return {
                    "type": "tool_calls",
                    "tool_calls": [{"id": "move", "name": "robot_move", "arguments": {"distance": 0.2}}],
                }
            if self.calls == 2:
                return {"type": "message", "text": "The robot is done."}
            if self.calls == 3:
                return {
                    "type": "tool_calls",
                    "tool_calls": [
                        {
                            "id": "status",
                            "name": "robot_get_action_status",
                            "arguments": {"action_id": "action_running"},
                        }
                    ],
                }
            if self.calls == 4:
                return {
                    "type": "tool_calls",
                    "tool_calls": [
                        {
                            "id": "status_again",
                            "name": "robot_get_action_status",
                            "arguments": {"action_id": "action_running"},
                        }
                    ],
                }
            return {"type": "message", "text": "The robot has now completed the motion."}

    result = GoalRunner(
        AsyncRobotModel(),
        max_steps=6,
        tool_names={"robot_move", "robot_get_action_status"},
        completion_verifier=RobotFeedbackVerifier(),
    ).run("move forward 0.2m")

    assert result["status"] == "completed"
    assert [event["tool"] for event in result["events"]] == [
        "robot_move",
        "robot_get_action_status",
        "robot_get_action_status",
    ]
    assert [item["achieved"] for item in result["verifications"]] == [False, True]


def test_semantic_critic_rejects_mismatch_then_accepts_correction(monkeypatch):
    monkeypatch.setenv("ROBOT_MODE", "simulated")
    monkeypatch.setattr("agent.execution.runner.record_tool_event", lambda event: None)
    handlers = __import__(
        "agent.scheduling.dispatcher", fromlist=["DISPATCHER"]
    ).DISPATCHER.handlers
    position = {"x": 0.0, "calls": 0}

    def move_handler(**arguments):
        position["calls"] += 1
        position["x"] += float(arguments["distance"])
        return json.dumps(
            {
                "action_id": f"action_{position['calls']}",
                "status": "succeeded",
                "ok": True,
                "message": "motion complete",
                "progress": 1.0,
                "state": {"stopped": True, "x": position["x"]},
                "data": {"command": {"action": "move", "params": arguments}},
            }
        )

    monkeypatch.setitem(handlers, "robot_move", move_handler)

    class DecisionAndCriticModel:
        def __init__(self):
            self.decision_calls = 0
            self.critic_calls = 0

        def complete(self, messages, tools, system_prompt=None):
            if (system_prompt or "").startswith("Robot completion critic."):
                self.critic_calls += 1
                if self.critic_calls == 1:
                    return {
                        "type": "message",
                        "text": (
                            "```json\n"
                            '{"achieved": false, "reason": "Only 0.05m was observed.", '
                            '"recommended_next_step": "Move the remaining 0.15m."}\n'
                            "```"
                        ),
                    }
                return {
                    "type": "message",
                    "text": (
                        '{"achieved": true, "reason": "The final x position is 0.20m.", '
                        '"recommended_next_step": ""}'
                    ),
                }

            self.decision_calls += 1
            if self.decision_calls == 1:
                return {
                    "type": "tool_calls",
                    "tool_calls": [{"id": "short", "name": "robot_move", "arguments": {"distance": 0.05}}],
                }
            if self.decision_calls == 2:
                return {"type": "message", "text": "The movement is complete."}
            if self.decision_calls == 3:
                return {
                    "type": "tool_calls",
                    "tool_calls": [{"id": "correct", "name": "robot_move", "arguments": {"distance": 0.15}}],
                }
            return {"type": "message", "text": "The requested 0.20m movement is complete."}

    model = DecisionAndCriticModel()
    result = GoalRunner(
        model,
        max_steps=5,
        tool_names={"robot_move"},
        completion_verifier=RobotFeedbackVerifier(critic_model=model),
    ).run("move forward 0.20m")

    assert result["status"] == "completed"
    assert result["stop_reason"] == "feedback_verified"
    assert [event["arguments"]["distance"] for event in result["events"]] == [0.05, 0.15]
    assert [item["source"] for item in result["verifications"]] == ["semantic_critic", "semantic_critic"]
    assert [item["achieved"] for item in result["verifications"]] == [False, True]
