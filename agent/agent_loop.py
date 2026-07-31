from __future__ import annotations

import sys
from typing import Any

from contracts.execution import ExecutionError, ExecutionRequest, ExecutionStatus

from .capabilities import CAPABILITY_REGISTRY
from .context import build_system_prompt
from .message_builder import (
    assistant_message,
    assistant_tool_call_message,
    tool_result_message,
    tool_result_text,
    user_message,
)
from .models import ModelAdapter
from .routing.intent_parser import (
    check_user_requested_arguments,
    final_tool_error_message,
    forced_plan_tool_calls,
    requested_task_action,
    should_stop_after_tool_error,
    should_stop_after_tool_success,
)
from .robot.policy import check_motion_against_latest_perception
from .scheduling import DISPATCHER
from .state.event_log import record_tool_event


def safe_print(text: str) -> None:
    try:
        print(text)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
        safe_text = text.encode(encoding, errors="replace").decode(encoding, errors="replace")
        print(safe_text)


class Agent:
    def __init__(self, model: ModelAdapter, max_steps: int = 8) -> None:
        self.model = model
        self.max_steps = max_steps
        self.messages: list[dict[str, Any]] = []
        self.last_events: list[dict[str, Any]] = []

    def run_turn(self, text: str) -> str:
        return self.run_turn_with_trace(text)["answer"]

    def run_turn_with_trace(self, text: str) -> dict[str, Any]:
        start_len = len(self.messages)
        self.last_events = []
        self.messages.append(user_message(text))

        try:
            forced_tool_calls = forced_plan_tool_calls(text)
            selected_names = {
                capability.tool_name for capability in CAPABILITY_REGISTRY.select(text)
            }
            if forced_tool_calls is not None:
                selected_names.update(str(call["name"]) for call in forced_tool_calls)
            selected_capabilities = tuple(
                capability
                for capability in CAPABILITY_REGISTRY.all()
                if capability.tool_name in selected_names
            )
            tool_schemas = CAPABILITY_REGISTRY.schemas_for_names(selected_names)
            capability_prompt = CAPABILITY_REGISTRY.prompt_summary(selected_capabilities)

            for _ in range(self.max_steps):
                system_prompt = build_system_prompt(self.messages) + "\n\n" + capability_prompt
                response = self.model.complete(self.messages, tool_schemas, system_prompt=system_prompt)
                if forced_tool_calls is not None:
                    response = {
                        "type": "tool_calls",
                        "tool_calls": forced_tool_calls,
                        "reasoning_content": response.get("reasoning_content"),
                    }

                if response["type"] == "message":
                    final_text = str(response.get("text", ""))
                    self.messages.append(assistant_message(final_text))
                    return {"answer": final_text, "events": self.last_events}

                tool_calls = response.get("tool_calls", [])
                self.messages.append(
                    assistant_tool_call_message(tool_calls, response.get("reasoning_content"))
                )

                for call in tool_calls:
                    name = call["name"]
                    arguments = call.get("arguments", {})
                    safe_print(f"> {name} {arguments}")
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
                        metadata={"tool_call_id": str(call.get("id", ""))},
                    )
                    event_details: dict[str, Any] = {
                        "tool": name,
                        "arguments": arguments,
                    }
                    stop_after_error = False
                    try:
                        if name not in selected_names:
                            raise PermissionError(f"Capability was not selected for this turn: {name}")
                        check_user_requested_arguments(name, arguments, text)
                        check_motion_against_latest_perception(name, arguments, self.last_events)
                        execution_event = DISPATCHER.dispatch(request)
                        result = tool_result_text(execution_event.result)
                        if execution_event.status is ExecutionStatus.FAILED:
                            stop_after_error = should_stop_after_tool_error(name, result, text)
                    except Exception as exc:
                        result = f"ERROR: {type(exc).__name__}: {exc}"
                        execution_event = request.event(
                            ExecutionStatus.FAILED,
                            result=result,
                            error=ExecutionError.from_exception(exc),
                        )
                        stop_after_error = should_stop_after_tool_error(name, result, text)
                    event = {**execution_event.to_dict(), **event_details}
                    self.last_events.append(event)
                    record_tool_event(event)
                    self.messages.append(tool_result_message(call["id"], name, result))

                    requested_task = requested_task_action(text)
                    if event["status"] == ExecutionStatus.SUCCEEDED.value and (
                        (requested_task is not None and name == requested_task["tool"])
                        or name == "create_task_plan"
                    ):
                        summary_prompt = build_system_prompt(self.messages) + (
                            "\n\nThe explicitly requested task tool has completed for this user turn. "
                            "Do not call any more tools. Explain the actual tool result naturally in the user's language. "
                            "State the resulting task or plan status and the next valid action, but do not claim that unexecuted actions occurred."
                        )
                        summary = self.model.complete(self.messages, [], system_prompt=summary_prompt)
                        if summary["type"] == "message":
                            answer = str(summary.get("text", ""))
                        else:
                            answer = f"任务操作已经完成：{result}\n\n本轮不会继续执行其他任务状态操作。"
                        self.messages.append(assistant_message(answer))
                        return {"answer": answer, "events": self.last_events}
                    if stop_after_error:
                        answer = final_tool_error_message(result)
                        self.messages.append(assistant_message(answer))
                        return {"answer": answer, "events": self.last_events}
                    if event["status"] == ExecutionStatus.SUCCEEDED.value and should_stop_after_tool_success(name, text):
                        self.messages.append(assistant_message(result))
                        return {"answer": result, "events": self.last_events}

            answer = "Stopped because max_steps was reached."
            self.messages.append(assistant_message(answer))
            return {"answer": answer, "events": self.last_events}
        except Exception:
            self.messages = self.messages[:start_len]
            self.last_events = []
            raise
