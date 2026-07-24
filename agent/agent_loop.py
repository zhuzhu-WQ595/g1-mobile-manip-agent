from __future__ import annotations

import re
import sys

from typing import Any

from .context import build_system_prompt
from .hooks import record_tool_event
from .message_builder import assistant_message, assistant_tool_call_message, tool_result_message, user_message
from .model_adapter import ModelAdapter
from .permissions import check_tool_call
from .tools import TOOL_HANDLERS, TOOL_SCHEMAS

#安全打印文本，处理 Unicode 编码错误。

def safe_print(text: str) -> None:
    try:
        print(text)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
        safe_text = text.encode(encoding, errors="replace").decode(encoding, errors="replace")
        print(safe_text)


def requested_preview_lines(text: str) -> int | None:
    patterns = [
        r"^(?:show|preview|read)\s+first\s+(\d+)\s+lines?\s+of\s+.+$",
        r"^preview\s+.+?\s+(\d+)\s+lines?$",
    ]
    for pattern in patterns:
        match = re.match(pattern, text.strip(), flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def requested_plan_execution(text: str) -> dict[str, Any] | None:
    stripped = text.strip()
    match = re.match(r"^execute next step of\s+(plan_\d+)$", stripped, flags=re.IGNORECASE)
    if match:
        return {"tool": "execute_next_plan_step", "plan_id": match.group(1)}

    match = re.match(r"^execute step\s+(\d+)\s+of\s+(plan_\d+)$", stripped, flags=re.IGNORECASE)
    if match:
        return {
            "tool": "execute_plan_step",
            "plan_id": match.group(2),
            "step_index": int(match.group(1)),
        }

    return None


def requested_blocked_resolution(text: str) -> dict[str, Any] | None:
    match = re.match(
        r"^resolve blocked step\s+(\d+)\s+of\s+(plan_\d+)\s+::\s*(.+)$",
        text.strip(),
        flags=re.DOTALL | re.IGNORECASE,
    )
    if not match:
        return None
    return {
        "tool": "resolve_blocked_step",
        "step_index": int(match.group(1)),
        "plan_id": match.group(2),
        "result": match.group(3).strip(),
    }


def requested_blocked_diagnosis(text: str) -> dict[str, Any] | None:
    match = re.match(
        r"^diagnose blocked step\s+(\d+)\s+of\s+(plan_\d+)$",
        text.strip(),
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    return {
        "tool": "diagnose_blocked_step",
        "step_index": int(match.group(1)),
        "plan_id": match.group(2),
    }


def requested_exact_tool(text: str) -> dict[str, Any] | None:
    lowered = text.strip().lower()
    if lowered in {"plans", "list plans"}:
        return {"tool": "list_plans", "arguments": {}}
    return None


def forced_plan_tool_calls(text: str) -> list[dict[str, Any]] | None:
    exact_tool = requested_exact_tool(text)
    if exact_tool is not None:
        return [
            {
                "id": "forced_exact_call_1",
                "name": exact_tool["tool"],
                "arguments": exact_tool["arguments"],
            }
        ]

    requested_plan = requested_plan_execution(text)
    requested_diagnosis = requested_blocked_diagnosis(text)
    if requested_diagnosis is not None:
        return [
            {
                "id": "forced_diagnosis_call_1",
                "name": requested_diagnosis["tool"],
                "arguments": {
                    "plan_id": requested_diagnosis["plan_id"],
                    "step_index": requested_diagnosis["step_index"],
                },
            }
        ]

    requested_resolution = requested_blocked_resolution(text)
    if requested_resolution is not None:
        return [
            {
                "id": "forced_resolution_call_1",
                "name": requested_resolution["tool"],
                "arguments": {
                    "plan_id": requested_resolution["plan_id"],
                    "step_index": requested_resolution["step_index"],
                    "result": requested_resolution["result"],
                },
            }
        ]

    if requested_plan is None:
        return None

    if requested_plan["tool"] == "execute_next_plan_step":
        arguments = {"plan_id": requested_plan["plan_id"]}
    else:
        arguments = {
            "plan_id": requested_plan["plan_id"],
            "step_index": requested_plan["step_index"],
        }

    return [
        {
            "id": "forced_plan_call_1",
            "name": requested_plan["tool"],
            "arguments": arguments,
        }
    ]


def check_user_requested_arguments(name: str, arguments: dict[str, Any], user_text: str) -> None:
    exact_tool = requested_exact_tool(user_text)
    if exact_tool is not None:
        if name != exact_tool["tool"]:
            raise PermissionError(f"This request must use {exact_tool['tool']} only.")
        return

    requested_plan = requested_plan_execution(user_text)
    requested_diagnosis = requested_blocked_diagnosis(user_text)
    if requested_diagnosis is not None:
        if name != requested_diagnosis["tool"]:
            raise PermissionError("This request must use diagnose_blocked_step.")
        if str(arguments.get("plan_id")) != requested_diagnosis["plan_id"]:
            raise PermissionError("Tool call changed the requested plan_id")
        if int(arguments.get("step_index", 0)) != requested_diagnosis["step_index"]:
            raise PermissionError("Tool call changed the requested step_index")
        return

    requested_resolution = requested_blocked_resolution(user_text)
    if requested_resolution is not None:
        if name != requested_resolution["tool"]:
            raise PermissionError("This request must use resolve_blocked_step.")
        if str(arguments.get("plan_id")) != requested_resolution["plan_id"]:
            raise PermissionError("Tool call changed the requested plan_id")
        if int(arguments.get("step_index", 0)) != requested_resolution["step_index"]:
            raise PermissionError("Tool call changed the requested step_index")
        if str(arguments.get("result", "")).strip() != requested_resolution["result"]:
            raise PermissionError("Tool call changed the user-provided result")
        return

    if requested_plan is not None:
        expected_tool = requested_plan["tool"]
        if name != expected_tool:
            raise PermissionError(
                f"This request must use {expected_tool}. "
                "Do not switch to another tool while executing a plan step."
            )
        if str(arguments.get("plan_id")) != requested_plan["plan_id"]:
            raise PermissionError("Tool call changed the requested plan_id")
        if expected_tool == "execute_plan_step" and int(arguments.get("step_index", 0)) != requested_plan["step_index"]:
            raise PermissionError("Tool call changed the requested step_index")
        return

    requested_lines = requested_preview_lines(user_text)
    if requested_lines is None:
        return

    if name != "preview_file_head":
        raise PermissionError(
            "First-N-lines requests must use preview_file_head. "
            "Do not switch to another tool after preview_file_head fails."
        )

    try:
        actual_lines = int(arguments.get("lines"))
    except (TypeError, ValueError) as exc:
        raise PermissionError("preview_file_head lines must match the user's requested line count") from exc

    if actual_lines != requested_lines:
        raise PermissionError(
            "Tool call changed the requested line count "
            f"from {requested_lines} to {actual_lines}. "
            "Do not retry with modified parameters unless the user confirms them."
        )


def should_stop_after_tool_error(name: str, result: str, user_text: str) -> bool:
    if requested_exact_tool(user_text) is not None:
        return True
    if requested_blocked_diagnosis(user_text) is not None:
        return True
    if requested_blocked_resolution(user_text) is not None:
        return True
    if requested_plan_execution(user_text) is not None:
        return True
    if requested_preview_lines(user_text) is None:
        return False
    if name != "preview_file_head":
        return True
    return "lines must be between 1 and 50" in result or "lines must be an integer" in result


def final_tool_error_message(result: str) -> str:
    return (
        f"{result}\n\n"
        "I will not retry with changed parameters or a different tool unless you confirm the new request."
    )


def should_stop_after_tool_success(name: str, user_text: str) -> bool:
    if name == "get_recent_tool_events":
        return True
    exact_tool = requested_exact_tool(user_text)
    if exact_tool is not None:
        return name == exact_tool["tool"]
    requested_diagnosis = requested_blocked_diagnosis(user_text)
    if requested_diagnosis is not None:
        return name == requested_diagnosis["tool"]
    requested_resolution = requested_blocked_resolution(user_text)
    if requested_resolution is not None:
        return name == requested_resolution["tool"]
    requested_plan = requested_plan_execution(user_text)
    return requested_plan is not None and name == requested_plan["tool"]


#初始化模型、messages、事件列表。
class Agent:
    def __init__(self, model: ModelAdapter, max_steps: int = 8) -> None:
        self.model = model
        self.max_steps = max_steps
        self.messages: list[dict[str, Any]] = []
        self.last_events: list[dict[str, Any]] = []

#说明它是简化版调用，仅返回回答文本。
    def run_turn(self, text: str) -> str:
        return self.run_turn_with_trace(text)["answer"]

#描述完整的对话循环流程、返回值结构和异常处理
    def run_turn_with_trace(self, text: str) -> dict[str, Any]:
        start_len = len(self.messages)
        self.last_events = []
        self.messages.append(user_message(text))##调用message_builder中的user_message函数

        try:
            for _ in range(self.max_steps):##循环max_steps次
                system_prompt = build_system_prompt(self.messages)##调用context中的build_system_prompt函数
                response = self.model.complete(self.messages, TOOL_SCHEMAS, system_prompt=system_prompt)##调用model_adapter中的complete函数
                forced_tool_calls = forced_plan_tool_calls(text)
                if forced_tool_calls is not None:
                    response = {"type": "tool_calls", "tool_calls": forced_tool_calls}
                
                # 不需要工具，直接返回文本
                if response["type"] == "message":
                    final_text = str(response.get("text", ""))
                    self.messages.append(assistant_message(final_text))
                    return {"answer": final_text, "events": self.last_events}
                
                # 需要工具调用
                tool_calls = response.get("tool_calls", [])
                self.messages.append(assistant_tool_call_message(tool_calls))
                
                #遍历每个工具调用
                for call in tool_calls:
                    name = call["name"]
                    arguments = call.get("arguments", {})
                    safe_print(f"> {name} {arguments}")
                    event: dict[str, Any] = {"tool": name, "arguments": arguments}
                    stop_after_error = False
                    try:
                        check_user_requested_arguments(name, arguments, text)
                        check_tool_call(name, arguments)#检查工具调用是否符合权限，调用permissions
                        handler = TOOL_HANDLERS[name]#获取工具调用的处理函数，调用tools
                        result = handler(**arguments)
                        event["status"] = "ok"
                    except Exception as exc:  # Keep tool failures inside the agent loop.
                        result = f"ERROR: {type(exc).__name__}: {exc}"
                        event["status"] = "error"
                        stop_after_error = should_stop_after_tool_error(name, result, text)
                    event["result"] = result
                    self.last_events.append(event)
                    record_tool_event(event)
                    self.messages.append(tool_result_message(call["id"], name, result))#把工具结果写回 messages，调用message_builder中的tool_result_message函数
                    if stop_after_error:
                        answer = final_tool_error_message(result)
                        self.messages.append(assistant_message(answer))
                        return {"answer": answer, "events": self.last_events}
                    if event["status"] == "ok" and should_stop_after_tool_success(name, text):
                        self.messages.append(assistant_message(result))
                        return {"answer": result, "events": self.last_events}
            
            #超过 max_steps
            answer = "Stopped because max_steps was reached."
            self.messages.append(assistant_message(answer))
            return {"answer": answer, "events": self.last_events}
        #未处理异常时回滚
        except Exception:
            self.messages = self.messages[:start_len]
            self.last_events = []
            raise
