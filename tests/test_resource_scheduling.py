from __future__ import annotations

import pytest

from agent.agent_loop import Agent
from agent.capabilities import CAPABILITY_REGISTRY
from agent.scheduling import ExecutionDispatcher, ResourceRegistry, ResourceSelector
from contracts.execution import ExecutionRequest, ExecutionStatus
from contracts.resource import ExecutionResource, ResourceStatus


def _resource(
    resource_id: str,
    *,
    load: float = 0.0,
    priority: int = 0,
    status: ResourceStatus = ResourceStatus.AVAILABLE,
) -> ExecutionResource:
    capability = CAPABILITY_REGISTRY.get("get_workspace_summary")
    return ExecutionResource(
        resource_id=resource_id,
        execution_target=capability.execution_target.value,
        capabilities=frozenset({capability.name}),
        status=status,
        load=load,
        priority=priority,
    )


def _request(resource_id: str | None = None) -> ExecutionRequest:
    capability = CAPABILITY_REGISTRY.get("get_workspace_summary")
    return ExecutionRequest(
        capability=capability.name,
        execution_target=capability.execution_target.value,
        resource_id=resource_id,
    )


def test_execution_resource_round_trip():
    resource = _resource("worker.alpha", load=0.25, priority=10)

    restored = ExecutionResource.from_dict(resource.to_dict())

    assert restored == resource
    assert restored.supports("workspace.get_workspace_summary", "local_toolkit") is True


def test_selector_prefers_available_low_load_then_priority():
    registry = ResourceRegistry(
        [
            _resource("worker.degraded", load=0.0, priority=100, status=ResourceStatus.DEGRADED),
            _resource("worker.busy", load=0.0, priority=100, status=ResourceStatus.BUSY),
            _resource("worker.high-load", load=0.8, priority=100),
            _resource("worker.low-priority", load=0.2, priority=1),
            _resource("worker.preferred", load=0.2, priority=5),
        ]
    )

    selection = ResourceSelector(registry).select(
        CAPABILITY_REGISTRY.get("get_workspace_summary")
    )

    assert selection.resource.resource_id == "worker.preferred"
    assert "automatic selection" in selection.reason


def test_explicit_resource_must_be_eligible_and_support_capability():
    registry = ResourceRegistry([_resource("worker.offline", status=ResourceStatus.OFFLINE)])

    with pytest.raises(RuntimeError, match="is offline"):
        ResourceSelector(registry).select(
            CAPABILITY_REGISTRY.get("get_workspace_summary"),
            "worker.offline",
        )


def test_registry_runtime_update_changes_selection():
    registry = ResourceRegistry(
        [_resource("worker.one", load=0.1), _resource("worker.two", load=0.2)]
    )
    selector = ResourceSelector(registry)
    capability = CAPABILITY_REGISTRY.get("get_workspace_summary")

    assert selector.select(capability).resource.resource_id == "worker.one"

    registry.update_runtime("worker.one", status=ResourceStatus.OFFLINE)

    assert selector.select(capability).resource.resource_id == "worker.two"


def test_dispatcher_executes_selected_resource_handler():
    registry = ResourceRegistry()
    dispatcher = ExecutionDispatcher(handlers={}, resource_registry=registry)
    called: list[str] = []

    def handler(request, capability, resource):
        called.append(resource.resource_id)
        return f"executed by {resource.resource_id}"

    dispatcher.register_resource(_resource("worker.one", load=0.7), handler)
    dispatcher.register_resource(_resource("worker.two", load=0.1), handler)

    event = dispatcher.dispatch(_request())

    assert event.status is ExecutionStatus.SUCCEEDED
    assert event.resource_id == "worker.two"
    assert event.result == "executed by worker.two"
    assert called == ["worker.two"]
    assert "load=0.10" in event.metadata["resource_selection"]


def test_dispatcher_rejects_request_when_no_resource_is_available():
    registry = ResourceRegistry([_resource("worker.busy", status=ResourceStatus.BUSY)])

    event = ExecutionDispatcher(handlers={}, resource_registry=registry).dispatch(_request())

    assert event.status is ExecutionStatus.FAILED
    assert event.error is not None
    assert event.error.code == "RuntimeError"
    assert "No available execution resource" in event.error.message


def test_agent_trace_records_automatically_selected_resource(monkeypatch):
    monkeypatch.setattr("agent.agent_loop.record_tool_event", lambda event: None)

    class SummaryModel:
        def __init__(self) -> None:
            self.calls = 0

        def complete(self, messages, tools, system_prompt=None):
            self.calls += 1
            if self.calls == 1:
                return {
                    "type": "tool_calls",
                    "tool_calls": [
                        {"id": "summary", "name": "get_workspace_summary", "arguments": {}}
                    ],
                }
            return {"type": "message", "text": "Workspace inspected."}

    trace = Agent(SummaryModel()).run_turn_with_trace("inspect the workspace")

    assert trace["events"][0]["resource_id"] == "local_toolkit.default"
    assert "automatic selection" in trace["events"][0]["metadata"]["resource_selection"]
