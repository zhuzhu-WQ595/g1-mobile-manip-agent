from __future__ import annotations

import os

from .base import ModelAdapter
from .deepseek import DeepSeekChatModel
from .demo import DemoModel
from .env import env_first, load_dotenv
from .openai_compatible import OpenAICompatibleChatModel


def load_model_from_env() -> ModelAdapter:
    load_dotenv()
    provider = os.environ.get("AGENT_PROVIDER", "").strip().lower()
    if not provider:
        base_url = env_first(("BASE_URL", "AGENT_BASE_URL", "DEEPSEEK_BASE_URL", "ANTHROPIC_BASE_URL"))
        provider = "deepseek" if "deepseek" in base_url.lower() else "demo"

    if provider == "demo":
        return DemoModel()
    if provider == "deepseek":
        return DeepSeekChatModel()
    if provider == "openai_compatible":
        return OpenAICompatibleChatModel()
    raise RuntimeError(f"Unknown AGENT_PROVIDER: {provider}")
