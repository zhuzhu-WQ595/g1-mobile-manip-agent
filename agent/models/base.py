from __future__ import annotations

from typing import Any, Protocol

from ..message_builder import parts_to_text


class ModelAdapter(Protocol):
    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        system_prompt: str | None = None,
    ) -> dict[str, Any]:
        ...


def latest_user_text(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user":
            return parts_to_text(message.get("content", []))
    return ""


def latest_tool_text(messages: list[dict[str, Any]]) -> str | None:
    for message in reversed(messages):
        if message.get("role") == "tool":
            return parts_to_text(message.get("content", []))
    return None
