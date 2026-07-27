from __future__ import annotations

import re
from typing import Any

from .base import latest_tool_text, latest_user_text


class DemoModel:
    """A deterministic local model for testing the agent loop without an API key."""

    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]], system_prompt: str | None = None) -> dict[str, Any]:
        tool_text = latest_tool_text(messages)
        if tool_text is not None and messages[-1].get("role") == "tool":
            if tool_text.startswith("ERROR:"):
                return {
                    "type": "message",
                    "text": (
                        "Tool failed:\n"
                        f"{tool_text}\n\n"
                        "I will not retry with changed parameters unless you confirm the new parameters."
                    ),
                }
            return {"type": "message", "text": f"Tool result:\n{tool_text}"}

        user_text = latest_user_text(messages).strip()
        lowered = user_text.lower()

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

        match = re.match(r"^approve\s+(approval_\d{3})$", lowered)
        if match:
            return self._tool("approve_pending_action", {"approval_id": match.group(1)})

        if lowered in {"approvals", "list approvals", "pending approvals"}:
            return self._tool("list_pending_approvals", {})

        match = re.match(r"^create plan\s+(.+?)\s+::\s*(.+)$", user_text, flags=re.DOTALL | re.IGNORECASE)
        if match:
            steps = [step.strip() for step in match.group(2).split(";") if step.strip()]
            return self._tool("create_plan", {"title": match.group(1).strip(), "steps": steps})

        if lowered in {"plans", "list plans"}:
            return self._tool("list_plans", {})

        match = re.match(r"^(?:suggest next step for|next step for)\s+(plan_\d+)$", lowered)
        if match:
            return self._tool("suggest_next_plan_step", {"plan_id": match.group(1)})

        match = re.match(r"^execute step\s+(\d+)\s+of\s+(plan_\d+)$", lowered)
        if match:
            return self._tool(
                "execute_plan_step",
                {"step_index": int(match.group(1)), "plan_id": match.group(2)},
            )

        match = re.match(r"^execute next step of\s+(plan_\d+)$", lowered)
        if match:
            return self._tool("execute_next_plan_step", {"plan_id": match.group(1)})

        match = re.match(r"^resolve blocked step\s+(\d+)\s+of\s+(plan_\d+)\s+::\s*(.+)$", user_text, flags=re.DOTALL | re.IGNORECASE)
        if match:
            return self._tool(
                "resolve_blocked_step",
                {
                    "step_index": int(match.group(1)),
                    "plan_id": match.group(2),
                    "result": match.group(3).strip(),
                },
            )

        match = re.match(r"^diagnose blocked step\s+(\d+)\s+of\s+(plan_\d+)$", lowered)
        if match:
            return self._tool(
                "diagnose_blocked_step",
                {"step_index": int(match.group(1)), "plan_id": match.group(2)},
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

        if lowered.startswith("create task "):
            return self._tool("create_task", {"title": user_text[12:].strip(), "detail": ""})

        if lowered in {"tasks", "list tasks"}:
            return self._tool("list_tasks", {})

        if lowered in {"skills", "list skills"}:
            return self._tool("list_skills", {})

        match = re.match(r"^(?:last|recent)\s+(\d+)\s+tool\s+(?:events|calls|logs)$", lowered)
        if match:
            return self._tool("get_recent_tool_events", {"limit": int(match.group(1))})

        if lowered in {"tool events", "recent tool events", "tool logs", "recent tool calls", "tool history"}:
            return self._tool("get_recent_tool_events", {})

        if lowered in {"python version", "python --version"}:
            return self._tool("run_command", {"command": "python --version"})

        return {
            "type": "message",
            "text": (
                "Demo model received your message. Try: list files, read README.md, "
                "show first 5 lines of README.md, write notes/hello.txt :: hello, "
                "overwrite notes/test.txt :: hello, edit notes/test.txt :: hello => hi, "
                "approve approval_001, count python files, "
                "create plan demo :: step one; step two, suggest next step for plan_123, execute next step of plan_123, plans, "
                "resolve blocked step 1 of plan_123 :: manual result, "
                "diagnose blocked step 1 of plan_123, "
                "save experiment note :: done, remember xxx, tasks, tool events, search xxx, or python version."
            ),
        }

    def _tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": "tool_calls",
            "tool_calls": [{"id": "demo_call_1", "name": name, "arguments": arguments}],
        }
