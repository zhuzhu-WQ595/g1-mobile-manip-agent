from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from ..message_builder import parts_to_text
from ..prompts import SYSTEM_PROMPT
from .env import env_first


class OpenAICompatibleChatModel:
    """Adapter for providers that support chat-completions style tool calls."""

    def __init__(
        self,
        *,
        provider_name: str = "openai_compatible",
        api_key_env: str = "AGENT_API_KEY",
        default_base_url: str = "https://api.openai.com/v1",
        default_model: str = "",
        api_key_aliases: tuple[str, ...] = (),
        model_envs: tuple[str, ...] = ("MODEL_ID", "AGENT_MODEL"),
        base_url_envs: tuple[str, ...] = ("BASE_URL", "AGENT_BASE_URL", "ANTHROPIC_BASE_URL"),
    ) -> None:
        self.provider_name = provider_name
        self.api_key_env = api_key_env
        self.api_key = env_first(("API_KEY", api_key_env, *api_key_aliases, "AGENT_API_KEY"))
        self.model = env_first(model_envs, default_model)
        self.base_url = env_first(base_url_envs, default_base_url).rstrip("/")
        if not self.api_key:
            aliases = ", ".join(("API_KEY", api_key_env, *api_key_aliases, "AGENT_API_KEY"))
            raise RuntimeError(f"API key is required for {provider_name}. Tried: {aliases}")
        if not self.model:
            raise RuntimeError(f"Model name is required for {provider_name}. Tried: {', '.join(model_envs)}")

    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]], system_prompt: str | None = None) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "messages": self._to_chat_messages(messages, system_prompt),
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        request = urllib.request.Request(
            url=f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Model API error {exc.code}: {body}") from exc

        message = data["choices"][0]["message"]
        reasoning_content = message.get("reasoning_content")
        tool_calls = message.get("tool_calls") or []
        if tool_calls:
            return {
                "type": "tool_calls",
                "reasoning_content": reasoning_content,
                "tool_calls": [
                    {
                        "id": call["id"],
                        "name": call["function"]["name"],
                        "arguments": json.loads(call["function"].get("arguments") or "{}"),
                    }
                    for call in tool_calls
                ],
            }
        return {
            "type": "message",
            "text": message.get("content") or "",
            "reasoning_content": reasoning_content,
        }

    def _to_chat_messages(self, messages: list[dict[str, Any]], system_prompt: str | None = None) -> list[dict[str, Any]]:
        chat_messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt or SYSTEM_PROMPT}]
        i = 0
        while i < len(messages):
            message = messages[i]
            role = message.get("role")
            if role == "user":
                chat_messages.append({"role": "user", "content": parts_to_text(message.get("content", []))})
                i += 1
                continue
            if role == "assistant" and message.get("tool_calls"):
                expected_ids = {str(call["id"]) for call in message["tool_calls"]}
                tool_messages: list[dict[str, Any]] = []
                j = i + 1
                while j < len(messages) and messages[j].get("role") == "tool":
                    tool_messages.append(messages[j])
                    j += 1
                found_ids = {str(tool.get("tool_call_id", "")) for tool in tool_messages}
                if expected_ids and expected_ids.issubset(found_ids):
                    assistant_tool_message = {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                                {
                                    "id": call["id"],
                                    "type": "function",
                                    "function": {
                                        "name": call["name"],
                                        "arguments": json.dumps(call.get("arguments", {})),
                                    },
                                }
                                for call in message["tool_calls"]
                            ],
                    }
                    if message.get("reasoning_content") is not None:
                        assistant_tool_message["reasoning_content"] = message["reasoning_content"]
                    chat_messages.append(assistant_tool_message)
                    for tool in tool_messages:
                        if str(tool.get("tool_call_id", "")) in expected_ids:
                            chat_messages.append(
                                {
                                    "role": "tool",
                                    "tool_call_id": tool["tool_call_id"],
                                    "content": parts_to_text(tool.get("content", [])),
                                }
                            )
                    i = j
                    continue
                i += 1
                continue
            if role == "assistant":
                chat_messages.append({"role": "assistant", "content": parts_to_text(message.get("content", []))})
                i += 1
                continue
            i += 1
        return chat_messages
