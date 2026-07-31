from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Iterable

from contracts.execution import (
    ExecutionError,
    ExecutionRequest,
    ExecutionStatus,
    normalize_execution_status,
)

from ..capabilities import CAPABILITY_REGISTRY
from ..context import build_system_prompt
from ..message_builder import (
    assistant_message,
    assistant_tool_call_message,
    tool_result_message,
    tool_result_text,
    user_message,
)
from ..models import ModelAdapter
from ..robot.policy import check_motion_against_latest_perception
from ..scheduling import DISPATCHER
from ..state.event_log import record_tool_event
from .prompts import GOAL_RULES
from .verification import CompletionVerifier


DEFAULT_GOAL_TOOLS = frozenset(
    {
        "list_files",
        "read_file",
        "search_files",
        "preview_file_head",
        "get_workspace_summary",
        "count_files_by_extension",
        "read_memory",
        "list_tasks",
        "get_task_details",
        "list_skills",
        "read_skill",
        "list_plans",
    }
)

ROBOT_GOAL_TOOLS = frozenset(
    {
        "robot_get_status",
        "robot_move",
        "robot_rotate",
        "robot_stop",
        "robot_get_action_status",
        "robot_cancel_action",
        "robot_emergency_stop",
        "robot_speak",
        "robot_capture_image",
        "perception_observe",
        "perception_check_path",
    }
)


@dataclass(frozen=True)
class ToolInterception:
    result: str
    status: str = "error"
    reason: str = "injected feedback"


ToolInterceptor = Callable[[int, str, dict[str, Any]], ToolInterception | None]


class GoalRunner:
    def __init__(
        self,
        model: ModelAdapter,
        max_steps: int = 8,
        tool_names: Iterable[str] = DEFAULT_GOAL_TOOLS,
        tool_interceptor: ToolInterceptor | None = None,
        completion_verifier: CompletionVerifier | None = None,
    ) -> None:
        self.model = model
        self.max_steps = max_steps
        self.tool_names = frozenset(tool_names)
        self.tool_interceptor = tool_interceptor
        self.completion_verifier = completion_verifier
        known_tools = {capability.tool_name for capability in CAPABILITY_REGISTRY.all()}
        unknown = self.tool_names - known_tools
        if unknown:
            raise ValueError(f"Unknown goal tools: {', '.join(sorted(unknown))}")
        self.tool_schemas = CAPABILITY_REGISTRY.schemas_for_names(self.tool_names)
        self.capability_prompt = CAPABILITY_REGISTRY.prompt_summary(
            CAPABILITY_REGISTRY.get(name) for name in self.tool_names
        )

    def run(self, goal: str) -> dict[str, Any]:
        clean_goal = goal.strip()
        if not clean_goal:
            raise ValueError("goal cannot be empty")

        run_id = "goal_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        messages = [user_message(clean_goal)]
        events: list[dict[str, Any]] = []
        verifications: list[dict[str, Any]] = []
        seen_calls: set[str] = set()

        for step in range(1, self.max_steps + 1):
            remaining = self.max_steps - step + 1
            prompt = build_system_prompt(messages) + "\n\n" + self.capability_prompt + "\n\n" + GOAL_RULES + (
                f"\n\nTool-step budget: this is step {step} of {self.max_steps}; "
                f"{remaining} tool step(s) remain."
            )
            response = self.model.complete(messages, self.tool_schemas, system_prompt=prompt)
            if response.get("type") == "message":
                answer = str(response.get("text", "")).strip()
                messages.append(assistant_message(answer))
                if self.completion_verifier is None:
                    return self._result(
                        run_id, clean_goal, "completed", "model_finished", answer, events, verifications
                    )
                verification = self.completion_verifier(clean_goal, answer, events)
                verifications.append(
                    {
                        "attempt": len(verifications) + 1,
                        "achieved": verification.achieved,
                        "reason": verification.reason,
                        "source": verification.source,
                    }
                )
                if verification.achieved:
                    return self._result(
                        run_id, clean_goal, "completed", "feedback_verified", answer, events, verifications
                    )
                if not verification.retryable or len(verifications) >= 2 or step == self.max_steps:
                    return self._result(
                        run_id,
                        clean_goal,
                        "blocked",
                        "completion_unverified",
                        verification.reason,
                        events,
                        verifications,
                    )
                messages.append(
                    user_message(
                        "Completion verifier rejected the proposed answer: "
                        + verification.reason
                        + " Continue from the latest feedback. Do not repeat a completed action."
                    )
                )
                continue

            calls = list(response.get("tool_calls", []))
            if not calls:
                answer = self._finish(messages, "No tool call or final answer was produced.")
                return self._result(
                    run_id, clean_goal, "blocked", "empty_model_action", answer, events, verifications
                )

            call = calls[0]
            name = str(call.get("name", ""))
            arguments = call.get("arguments", {})
            if not isinstance(arguments, dict):
                arguments = {}
            signature = json.dumps({"tool": name, "arguments": arguments}, ensure_ascii=False, sort_keys=True)
            if signature in seen_calls and not _can_repeat_status_poll(name, arguments, events):
                reason = f"The model repeated {name} with unchanged arguments, so execution stopped."
                answer = self._finish(messages, reason)
                return self._result(
                    run_id, clean_goal, "blocked", "repeated_action", answer, events, verifications
                )
            seen_calls.add(signature)

            selected_call = {
                "id": str(call.get("id") or f"goal_call_{step}"),
                "name": name,
                "arguments": arguments,
            }
            messages.append(assistant_tool_call_message([selected_call], response.get("reasoning_content")))

            capability = None
            try:
                capability = CAPABILITY_REGISTRY.get(name)
            except KeyError:
                pass
            request = ExecutionRequest(
                capability=capability.name if capability is not None else f"unknown.{name}",
                execution_target=(
                    capability.execution_target.value if capability is not None else "unknown"
                ),
                arguments=arguments,
                metadata={"run_id": run_id, "step": step},
            )
            event_details: dict[str, Any] = {
                "mode": "goal",
                "run_id": run_id,
                "step": step,
                "tool": name,
                "arguments": arguments,
                "proposed_tool_calls": len(calls),
            }
            print(f"> step {step}: {name} {arguments}")
            try:
                if name not in self.tool_names:
                    raise PermissionError(f"Tool is not enabled in goal mode: {name}")
                check_motion_against_latest_perception(name, arguments, events)
                interception = (
                    self.tool_interceptor(step, name, arguments)
                    if self.tool_interceptor is not None
                    else None
                )
                if interception is not None:
                    result = interception.result
                    execution_status = normalize_execution_status(interception.status)
                    error = (
                        ExecutionError(
                            code="injected_feedback",
                            message=result,
                            retryable=True,
                            details={"reason": interception.reason},
                        )
                        if execution_status is ExecutionStatus.FAILED
                        else None
                    )
                    execution_event = request.event(
                        execution_status,
                        result=result,
                        error=error,
                    )
                    event_details["injected"] = True
                    event_details["injection_reason"] = interception.reason
                else:
                    execution_event = DISPATCHER.dispatch(request)
                    result = tool_result_text(execution_event.result)
            except Exception as exc:
                result = f"ERROR: {type(exc).__name__}: {exc}"
                execution_event = request.event(
                    ExecutionStatus.FAILED,
                    result=result,
                    error=ExecutionError.from_exception(exc),
                )
            event = {**execution_event.to_dict(), **event_details}
            events.append(event)
            record_tool_event(event)
            messages.append(tool_result_message(selected_call["id"], name, result))
            if event["status"] == ExecutionStatus.FAILED.value and _is_permission_denial(str(result)):
                answer = self._finish(
                    messages,
                    "A permission or policy denial is terminal; alternate tools must not be used to bypass it.",
                )
                return self._result(
                    run_id, clean_goal, "blocked", "permission_denied", answer, events, verifications
                )

        answer = self._finish(
            messages,
            f"The execution budget of {self.max_steps} tool steps was exhausted.",
        )
        return self._result(
            run_id, clean_goal, "max_steps", "step_budget_exhausted", answer, events, verifications
        )

    def _finish(self, messages: list[dict[str, Any]], reason: str) -> str:
        prompt = build_system_prompt(messages) + "\n\n" + GOAL_RULES + (
            "\n\nExecution has stopped: " + reason
            + " Summarize verified evidence, state whether the goal was achieved, and explain any blocker. "
            "Do not claim that another tool was executed."
        )
        response = self.model.complete(messages, [], system_prompt=prompt)
        if response.get("type") == "message":
            text = str(response.get("text", "")).strip()
            if text and not _looks_like_tool_request(text):
                return text
        return reason

    @staticmethod
    def _result(
        run_id: str,
        goal: str,
        status: str,
        stop_reason: str,
        answer: str,
        events: list[dict[str, Any]],
        verifications: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        return {
            "run_id": run_id,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "goal": goal,
            "status": status,
            "stop_reason": stop_reason,
            "answer": answer,
            "steps_executed": len(events),
            "events": events,
            "verifications": verifications or [],
        }


def _looks_like_tool_request(text: str) -> bool:
    lowered = text.lower()
    return "dsml" in lowered or "<|tool" in lowered or "tool_calls>" in lowered


def _is_permission_denial(result: str) -> bool:
    lowered = result.lower()
    return "permissionerror" in lowered or "permission denied" in lowered or "policy denial" in lowered


def _can_repeat_status_poll(
    name: str,
    arguments: dict[str, Any],
    events: list[dict[str, Any]],
) -> bool:
    if name != "robot_get_action_status":
        return False
    for event in reversed(events):
        if event.get("tool") != name or event.get("arguments") != arguments:
            continue
        try:
            feedback = json.loads(str(event.get("result", "")))
        except (json.JSONDecodeError, TypeError):
            return False
        return isinstance(feedback, dict) and feedback.get("status") in {"pending", "running"}
    return False
