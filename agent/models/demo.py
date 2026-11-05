from __future__ import annotations

import json
import re
from typing import Any

from ..routing.intent_parser import (
    PLAN_REF_PATTERN,
    TASK_REF_PATTERN,
    clean_plan_ref,
    clean_task_ref,
    natural_task_cycle_arguments,
)
from .base import latest_tool_text, latest_user_text


class DemoModel:
    """A deterministic local model for testing the agent loop without an API key."""

    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]], system_prompt: str | None = None) -> dict[str, Any]:
        user_text = latest_user_text(messages).strip()
        tool_text = latest_tool_text(messages)
        if tool_text is not None and messages[-1].get("role") == "tool":
            tool_name = str(messages[-1].get("name", ""))
            conditional_move = self._conditional_move_arguments(user_text)
            if tool_name == "perception_check_path" and conditional_move is not None:
                if tool_text.startswith("ERROR:"):
                    return {
                        "type": "message",
                        "text": "感知失败，无法确认路径安全，因此不会执行移动。\n" + tool_text,
                    }
                try:
                    observation = json.loads(tool_text)
                except json.JSONDecodeError:
                    observation = {}
                if isinstance(observation, dict) and observation.get("path_clear") is True:
                    return self._tool("robot_move", conditional_move)
                return {
                    "type": "message",
                    "text": "感知结果显示路径不安全，因此未执行移动。",
                }
            if tool_name in {"robot_move", "robot_get_action_status"} and conditional_move is not None:
                try:
                    feedback = json.loads(tool_text)
                except json.JSONDecodeError:
                    feedback = {}
                status = str(feedback.get("status", "")) if isinstance(feedback, dict) else ""
                action_id = str(feedback.get("action_id", "")) if isinstance(feedback, dict) else ""
                if status in {"pending", "running"} and action_id:
                    return self._tool("robot_get_action_status", {"action_id": action_id})
                if status == "succeeded":
                    return {"type": "message", "text": "路径检查通过，机器人移动已完成。"}
                return {"type": "message", "text": "机器人移动未成功完成，不再继续执行。"}
            if tool_text.startswith("ERROR:"):
                return {
                    "type": "message",
                    "text": (
                        "工具执行失败：\n"
                        f"{tool_text}\n\n"
                        "我不会自动更换参数重试，除非你确认新的请求。"
                    ),
                }
            return {"type": "message", "text": f"工具结果：\n{tool_text}"}

        lowered = user_text.lower()

        if lowered in {"help", "what can you do", "what can you do?", "你会做什么", "你能做什么", "你可以做什么", "帮助"}:
            return {"type": "message", "text": self._capability_text()}

        if "中文" in user_text and any(token in user_text for token in ("回答", "回复", "说")):
            return {
                "type": "message",
                "text": "好的。当前 Web 演示模式使用本地规则模型，我会优先用中文说明，并在需要验证功能时调用对应工具。",
            }

        if lowered in {"list files", "ls", "dir", "列目录"}:
            return self._tool("list_files", {"path": "."})

        match = re.match(r"^(?:show|preview|read)\s+first\s+(\d+)\s+lines?\s+of\s+(.+)$", user_text, flags=re.IGNORECASE)
        if match:
            return self._tool(
                "preview_file_head",
                {"lines": int(match.group(1)), "path": match.group(2).strip()},
            )

        match = re.match(r"^preview\s+(.+?)\s+(\d+)\s+lines?$", user_text, flags=re.IGNORECASE)
        if match:
            return self._tool(
                "preview_file_head",
                {"path": match.group(1).strip(), "lines": int(match.group(2))},
            )

        if lowered.startswith("read "):
            return self._tool("read_file", {"path": user_text[5:].strip()})

        match = re.match(r"^write\s+(.+?)\s+::\s*(.*)$", user_text, flags=re.DOTALL | re.IGNORECASE)
        if match:
            return self._tool("write_file", {"path": match.group(1).strip(), "content": match.group(2)})

        match = re.match(r"^overwrite\s+(.+?)\s+::\s*(.*)$", user_text, flags=re.DOTALL | re.IGNORECASE)
        if match:
            return self._tool(
                "request_overwrite_file",
                {"path": match.group(1).strip(), "content": match.group(2)},
            )

        match = re.match(r"^edit\s+(.+?)\s+::\s*(.*?)\s+=>\s+(.*)$", user_text, flags=re.DOTALL | re.IGNORECASE)
        if match:
            return self._tool(
                "request_edit_file",
                {
                    "path": match.group(1).strip(),
                    "old_text": match.group(2),
                    "new_text": match.group(3),
                },
            )

        match = re.match(r"^approve\s+(approval_\d+)$", lowered)
        if match:
            return self._tool("approve_pending_action", {"approval_id": match.group(1)})

        match = re.match(r"^(?:cancel|reject)\s+(approval_\d+)$", lowered)
        if match:
            return self._tool("cancel_pending_action", {"approval_id": match.group(1)})

        match = re.match(r"^(?:approval details|show approval|approval)\s+(approval_\d+)$", lowered)
        if match:
            return self._tool("get_approval_details", {"approval_id": match.group(1)})

        match = re.match(r"^(?:last|recent)\s+(\d+)\s+approvals?$", lowered)
        if match:
            return self._tool("list_approval_history", {"limit": int(match.group(1))})

        if lowered in {"approval history", "recent approvals", "all approvals"}:
            return self._tool("list_approval_history", {})

        if lowered in {"approvals", "list approvals", "pending approvals"}:
            return self._tool("list_pending_approvals", {})

        match = re.match(r"^create plan\s+(.+?)\s+::\s*(.+)$", user_text, flags=re.DOTALL | re.IGNORECASE)
        if match:
            steps = [step.strip() for step in match.group(2).split(";") if step.strip()]
            return self._tool("create_plan", {"title": match.group(1).strip(), "steps": steps})

        if lowered in {"plans", "list plans"}:
            return self._tool("list_plans", {})

        match = re.match(
            r"^(?:run task|run cycle|execute task cycle)\s+(.+?)(?:\s+::\s*(.+))?$",
            user_text,
            flags=re.DOTALL | re.IGNORECASE,
        )
        if not match:
            match = re.match(r"^(?:运行任务|执行任务周期|完整执行任务)\s+(.+?)(?:\s+::\s*(.+))?$", user_text, flags=re.DOTALL)
        if match:
            steps = [step.strip() for step in (match.group(2) or "").split(";") if step.strip()]
            arguments: dict[str, Any] = {"title": match.group(1).strip()}
            if steps:
                arguments["steps"] = steps
            return self._tool("run_task_cycle", arguments)

        natural_cycle = natural_task_cycle_arguments(user_text)
        if natural_cycle is not None:
            return self._tool("run_task_cycle", natural_cycle)

        plan_ref = PLAN_REF_PATTERN
        match = re.match(rf"^(?:suggest next step for|next step for)\s+{plan_ref}$", user_text, flags=re.IGNORECASE)
        if match:
            return self._tool("suggest_next_plan_step", {"plan_id": clean_plan_ref(match.group(1))})

        match = re.match(rf"^execute step\s+(\d+)\s+of\s+{plan_ref}$", user_text, flags=re.IGNORECASE)
        if match:
            return self._tool(
                "execute_plan_step",
                {"step_index": int(match.group(1)), "plan_id": clean_plan_ref(match.group(2))},
            )

        match = re.match(rf"^execute next step of\s+{plan_ref}$", user_text, flags=re.IGNORECASE)
        if not match:
            match = re.match(rf"^执行{plan_ref}下一步$", user_text)
        if match:
            return self._tool("execute_next_plan_step", {"plan_id": clean_plan_ref(match.group(1))})

        match = re.match(
            rf"^resolve blocked step\s+(\d+)\s+of\s+{plan_ref}\s+::\s*(.+)$",
            user_text,
            flags=re.DOTALL | re.IGNORECASE,
        )
        if match:
            return self._tool(
                "resolve_blocked_step",
                {
                    "step_index": int(match.group(1)),
                    "plan_id": clean_plan_ref(match.group(2)),
                    "result": match.group(3).strip(),
                },
            )

        match = re.match(rf"^diagnose blocked step\s+(\d+)\s+of\s+{plan_ref}$", user_text, flags=re.IGNORECASE)
        if match:
            return self._tool(
                "diagnose_blocked_step",
                {"step_index": int(match.group(1)), "plan_id": clean_plan_ref(match.group(2))},
            )

        match = re.match(r"^update plan\s+(plan_\d+)\s+step\s+(\d+)\s+(pending|in_progress|done|blocked)$", lowered)
        if match:
            return self._tool(
                "update_plan_step",
                {"plan_id": match.group(1), "step_index": int(match.group(2)), "status": match.group(3)},
            )

        if lowered.startswith("append ") and " :: " in user_text:
            target, content = user_text[7:].split(" :: ", 1)
            return self._tool("append_file", {"path": target.strip(), "content": content})

        if lowered.startswith("search "):
            return self._tool("search_files", {"path": ".", "query": user_text[7:].strip()})

        if lowered in {
            "get workspace summary",
            "workspace summary",
            "summarize workspace",
            "workspace stats",
            "project summary",
        }:
            return self._tool("get_workspace_summary", {})

        extension_aliases = {
            "python": ".py",
            "py": ".py",
            ".py": ".py",
            "markdown": ".md",
            "md": ".md",
            ".md": ".md",
            "text": ".txt",
            "txt": ".txt",
            ".txt": ".txt",
            "html": ".html",
            ".html": ".html",
            "css": ".css",
            ".css": ".css",
            "javascript": ".js",
            "js": ".js",
            ".js": ".js",
        }
        match = re.match(r"^count\s+(.+?)\s+files?$", lowered)
        if match:
            requested = match.group(1).strip()
            return self._tool("count_files_by_extension", {"extension": extension_aliases.get(requested, requested)})

        if lowered.startswith("remember "):
            return self._tool("remember_memory", {"text": user_text[9:].strip()})

        match = re.match(r"^(?:save|record|log)\s+experiment\s+note\s+::\s*(.+)$", user_text, flags=re.DOTALL | re.IGNORECASE)
        if match:
            return self._tool("save_experiment_note", {"note": match.group(1).strip()})

        if lowered in {"memory", "read memory"}:
            return self._tool("read_memory", {})

        match = re.match(r"^(?:创建任务|新建任务)\s+(.+?)(?:\s+::\s*(.*))?$", user_text, flags=re.DOTALL)
        if match:
            return self._tool(
                "create_task",
                {"title": match.group(1).strip(), "detail": (match.group(2) or "").strip()},
            )

        task_ref = TASK_REF_PATTERN
        plan_patterns = [
            (rf"^为(?:任务)?\s*{task_ref}\s*创建计划\s*::\s*(.+)$", "create_task_plan"),
            (rf"^验证(?:任务)?\s*{task_ref}\s*(?:的)?计划$", "validate_task_plan"),
            (rf"^查看(?:任务)?\s*{task_ref}\s*(?:的)?计划$", "get_task_plan"),
        ]
        for pattern, tool in plan_patterns:
            match = re.match(pattern, user_text, flags=re.DOTALL)
            if not match:
                continue
            arguments: dict[str, Any] = {"task_id": clean_task_ref(match.group(1))}
            if tool == "create_task_plan":
                arguments["steps"] = [step.strip() for step in match.group(2).split(";") if step.strip()]
            return self._tool(tool, arguments)

        lifecycle_patterns = [
            (rf"^查看(?:任务)?\s*{task_ref}\s*(?:的)?详情$", "get_task_details", None),
            (rf"^开始(?:任务)?\s*{task_ref}$", "start_task", None),
            (rf"^重试(?:任务)?\s*{task_ref}$", "retry_task", None),
            (rf"^完成(?:任务)?\s*{task_ref}(?:\s+::\s*(.*))?$", "complete_task", "result"),
            (rf"^标记(?:任务)?\s*{task_ref}\s*失败\s*::\s*(.+)$", "fail_task", "error"),
            (rf"^取消(?:任务)?\s*{task_ref}(?:\s+::\s*(.*))?$", "cancel_task", "reason"),
        ]
        for pattern, tool, field in lifecycle_patterns:
            match = re.match(pattern, user_text, flags=re.DOTALL)
            if not match:
                continue
            arguments = {"task_id": clean_task_ref(match.group(1))}
            if field:
                arguments[field] = (match.group(2) or "").strip()
            return self._tool(tool, arguments)

        if user_text in {"任务", "任务列表", "列出任务"}:
            return self._tool("list_tasks", {})

        match = re.match(
            r"^create task plan\s+<?(task_\d+)>?\s+::\s*(.+)$",
            user_text,
            flags=re.DOTALL | re.IGNORECASE,
        )
        if not match:
            match = re.match(r"^为任务\s*<?(task_\d+)>?\s*创建计划\s*::\s*(.+)$", user_text, flags=re.DOTALL)
        if match:
            steps = [step.strip() for step in match.group(2).split(";") if step.strip()]
            return self._tool("create_task_plan", {"task_id": match.group(1).lower(), "steps": steps})

        match = re.match(r"^validate task plan\s+<?(task_\d+)>?$", user_text, flags=re.IGNORECASE)
        if match:
            return self._tool("validate_task_plan", {"task_id": match.group(1).lower()})

        match = re.match(r"^(?:task plan|show task plan)\s+<?(task_\d+)>?$", user_text, flags=re.IGNORECASE)
        if not match:
            match = re.match(r"^查看(?:任务)?\s*<?(task_\d+)>?\s*(?:的)?计划$", user_text)
        if match:
            return self._tool("get_task_plan", {"task_id": match.group(1).lower()})

        match = re.match(r"^create task\s+(.+?)(?:\s+::\s*(.*))?$", user_text, flags=re.DOTALL | re.IGNORECASE)
        if match:
            return self._tool(
                "create_task",
                {"title": match.group(1).strip(), "detail": (match.group(2) or "").strip()},
            )

        match = re.match(r"^(?:创建任务|新建任务)\s+(.+?)(?:\s+::\s*(.*))?$", user_text, flags=re.DOTALL)
        if match:
            return self._tool(
                "create_task",
                {"title": match.group(1).strip(), "detail": (match.group(2) or "").strip()},
            )

        if lowered in {"tasks", "list tasks"} or user_text in {"任务", "任务列表", "列出任务"}:
            return self._tool("list_tasks", {})

        match = re.match(r"^(?:task details|show task|task)\s+(task_\d+)$", lowered)
        if match:
            return self._tool("get_task_details", {"task_id": match.group(1)})

        match = re.match(r"^查看(?:任务)?\s*(task_\d+)\s*(?:的)?详情$", user_text)
        if match:
            return self._tool("get_task_details", {"task_id": match.group(1)})

        match = re.match(r"^start(?: task)?\s+(task_\d+)$", lowered)
        if match:
            return self._tool("start_task", {"task_id": match.group(1)})

        match = re.match(r"^开始(?:任务)?\s*(task_\d+)$", user_text)
        if match:
            return self._tool("start_task", {"task_id": match.group(1)})

        match = re.match(r"^complete(?: task)?\s+(task_\d+)(?:\s+::\s*(.*))?$", user_text, flags=re.DOTALL | re.IGNORECASE)
        if match:
            return self._tool(
                "complete_task",
                {"task_id": match.group(1).lower(), "result": (match.group(2) or "").strip()},
            )

        match = re.match(r"^完成(?:任务)?\s*(task_\d+)(?:\s+::\s*(.*))?$", user_text, flags=re.DOTALL)
        if match:
            return self._tool(
                "complete_task",
                {"task_id": match.group(1), "result": (match.group(2) or "").strip()},
            )

        match = re.match(r"^fail(?: task)?\s+(task_\d+)\s+::\s*(.+)$", user_text, flags=re.DOTALL | re.IGNORECASE)
        if match:
            return self._tool("fail_task", {"task_id": match.group(1).lower(), "error": match.group(2).strip()})

        match = re.match(r"^标记(?:任务)?\s*(task_\d+)\s*失败\s*::\s*(.+)$", user_text, flags=re.DOTALL)
        if match:
            return self._tool("fail_task", {"task_id": match.group(1), "error": match.group(2).strip()})

        match = re.match(r"^retry(?: task)?\s+(task_\d+)$", lowered)
        if match:
            return self._tool("retry_task", {"task_id": match.group(1)})

        match = re.match(r"^重试(?:任务)?\s*(task_\d+)$", user_text)
        if match:
            return self._tool("retry_task", {"task_id": match.group(1)})

        match = re.match(r"^cancel(?: task)?\s+(task_\d+)(?:\s+::\s*(.*))?$", user_text, flags=re.DOTALL | re.IGNORECASE)
        if match:
            return self._tool(
                "cancel_task",
                {"task_id": match.group(1).lower(), "reason": (match.group(2) or "").strip()},
            )

        match = re.match(r"^取消(?:任务)?\s*(task_\d+)(?:\s+::\s*(.*))?$", user_text, flags=re.DOTALL)
        if match:
            return self._tool(
                "cancel_task",
                {"task_id": match.group(1), "reason": (match.group(2) or "").strip()},
            )

        if lowered in {"skills", "list skills"}:
            return self._tool("list_skills", {})

        match = re.match(r"^(?:last|recent)\s+(\d+)\s+tool\s+(?:events|calls|logs)$", lowered)
        if match:
            return self._tool("get_recent_tool_events", {"limit": int(match.group(1))})

        if lowered in {"tool events", "recent tool events", "tool logs", "recent tool calls", "tool history"}:
            return self._tool("get_recent_tool_events", {})

        if lowered in {"python version", "python --version"}:
            return self._tool("run_command", {"command": "python --version"})

        if lowered in {"observe environment", "perception observe", "观察环境", "感知环境"}:
            return self._tool("perception_observe", {"source": "front_sensor"})

        conditional_move = self._conditional_move_arguments(user_text)
        if conditional_move is not None:
            return self._tool(
                "perception_check_path",
                {
                    "direction": conditional_move["direction"],
                    "distance": conditional_move["distance"],
                },
            )

        match = re.match(
            r"^check path\s+(forward|backward)\s+([0-9]+(?:\.[0-9]+)?)$",
            lowered,
        )
        if match:
            return self._tool(
                "perception_check_path",
                {"direction": match.group(1), "distance": float(match.group(2))},
            )

        match = re.match(
            r"^call service\s+([A-Za-z0-9_.-]+)\s+operation\s+([A-Za-z0-9_.-]+)(?:\s+::\s*(.+))?$",
            user_text,
            flags=re.DOTALL | re.IGNORECASE,
        )
        if match:
            payload_text = (match.group(3) or "{}").strip()
            try:
                payload = json.loads(payload_text)
            except json.JSONDecodeError:
                return {"type": "message", "text": "远程服务参数必须是 JSON 对象。"}
            if not isinstance(payload, dict):
                return {"type": "message", "text": "远程服务参数必须是 JSON 对象。"}
            return self._tool(
                "invoke_remote_service",
                {
                    "service": match.group(1),
                    "operation": match.group(2),
                    "payload": payload,
                },
            )

        return {
            "type": "message",
            "text": self._fallback_text(),
        }

    def _tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": "tool_calls",
            "tool_calls": [{"id": "demo_call_1", "name": name, "arguments": arguments}],
        }

    @staticmethod
    def _conditional_move_arguments(text: str) -> dict[str, Any] | None:
        lowered = text.lower()
        conditional = any(
            marker in lowered
            for marker in ("only if", "if clear", "if safe", "如果安全", "路径安全", "安全才")
        )
        if not conditional:
            return None
        match = re.search(
            r"\b(forward|backward)\s+([0-9]+(?:\.[0-9]+)?)\s*(?:m|meter|meters)?\b",
            lowered,
        )
        if match:
            return {
                "direction": match.group(1),
                "distance": float(match.group(2)),
                "speed": 0.1,
            }
        match = re.search(r"向(前|后)移动\s*([0-9]+(?:\.[0-9]+)?)\s*米", text)
        if match:
            return {
                "direction": "forward" if match.group(1) == "前" else "backward",
                "distance": float(match.group(2)),
                "speed": 0.1,
            }
        return None

    def _capability_text(self) -> str:
        return (
            "我现在运行在本地演示模式，主要用于验证 Agent 的核心流程。\n\n"
            "我可以帮助你验证：\n"
            "- 工作区摘要、文件读取、文件搜索和文件数量统计\n"
            "- 工具调用参数是否正确\n"
            "- 文件覆盖前的审批流程\n"
            "- 多步计划的创建、执行、结果写回和失败诊断\n"
            "- 任务状态、实验记录和工具调用日志\n\n"
            "- 通过服务白名单调用外部 HTTP 软件能力\n\n"
            "- 通过独立感知服务获取结构化环境与路径观察\n\n"
            "注意：当前 Web 模式默认使用规则型 demo 模型，不是真正的大模型闲聊能力。"
            "如果要更自然的中文理解和自由问答，需要切换到真实模型。"
        )

    def _fallback_text(self) -> str:
        return (
            "当前是本地 demo 模型，我没有命中这句话对应的固定规则。\n\n"
            "你可以试试这些指令：\n"
            "- get workspace summary\n"
            "- plans\n"
            "- count python files\n"
            "- show first 5 lines of README.md\n"
            "- create plan demo :: 统计 Python 文件; 统计 Markdown 文件; 汇总结果\n"
            "- execute next step of plan_xxx\n"
            "- diagnose blocked step 1 of plan_xxx\n\n"
            "如果你想让我像真实智能体一样自由理解中文问题，需要把 Web 模式切换到真实大模型。"
        )
