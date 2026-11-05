import os

from agent.web_server import configure_web_provider, resource_status_payload


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


def test_web_resource_status_payload_is_structured():
    payload = resource_status_payload()

    assert payload["total"] == len(payload["resources"])
    assert sum(payload["counts"].values()) == payload["total"]
    assert all("resource_id" in resource for resource in payload["resources"])
    assert all("consecutive_failures" in resource for resource in payload["resources"])
