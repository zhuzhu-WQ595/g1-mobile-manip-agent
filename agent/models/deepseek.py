from __future__ import annotations

from .openai_compatible import OpenAICompatibleChatModel


class DeepSeekChatModel(OpenAICompatibleChatModel):
    """DeepSeek adapter using its OpenAI-compatible chat completions API."""

    def __init__(self) -> None:
        super().__init__(
            provider_name="deepseek",
            api_key_env="DEEPSEEK_API_KEY",
            default_base_url="https://api.deepseek.com",
            default_model="deepseek-v4-flash",
            api_key_aliases=("ANTHROPIC_API_KEY",),
            model_envs=("MODEL_ID", "AGENT_MODEL", "DEEPSEEK_MODEL"),
            base_url_envs=("BASE_URL", "AGENT_BASE_URL", "DEEPSEEK_BASE_URL", "ANTHROPIC_BASE_URL"),
        )
        if self.base_url.endswith("/anthropic"):
            self.base_url = self.base_url[: -len("/anthropic")]
