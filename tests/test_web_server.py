import os

from agent.web_server import configure_web_provider


def test_web_server_keeps_configured_agent_provider(monkeypatch):
    monkeypatch.setenv("AGENT_PROVIDER", "deepseek")
    monkeypatch.delenv("AGENT_WEB_PROVIDER", raising=False)

    configure_web_provider()

    assert os.environ["AGENT_PROVIDER"] == "deepseek"


def test_web_specific_provider_explicitly_overrides_agent_provider(monkeypatch):
    monkeypatch.setenv("AGENT_PROVIDER", "deepseek")
    monkeypatch.setenv("AGENT_WEB_PROVIDER", "demo")

    configure_web_provider()

    assert os.environ["AGENT_PROVIDER"] == "demo"
