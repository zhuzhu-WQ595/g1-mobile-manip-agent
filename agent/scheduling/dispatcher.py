from __future__ import annotations

from collections.abc import Callable, MutableMapping
from dataclasses import replace
from typing import Any

from contracts.capability import CapabilitySpec, CapabilityTarget
from contracts.execution import ExecutionError, ExecutionEvent, ExecutionRequest, ExecutionStatus

from ..capabilities import CAPABILITY_REGISTRY, CapabilityRegistry
from ..permissions import check_tool_call
from ..toolkit import TOOL_HANDLERS
from .remote import HttpRemoteServiceExecutor


ExecutionTargetHandler = Callable[[ExecutionRequest, CapabilitySpec], Any]


class ExecutionDispatcher:
    """Validate and route one execution request to its declared target."""

    def __init__(
        self,
        handlers: MutableMapping[str, Callable[..., Any]] | None = None,
        capability_registry: CapabilityRegistry = CAPABILITY_REGISTRY,
    ) -> None:
        self.handlers = handlers if handlers is not None else TOOL_HANDLERS
        self.capability_registry = capability_registry
        self._target_handlers: dict[str, ExecutionTargetHandler] = {
            CapabilityTarget.LOCAL_TOOLKIT.value: self._execute_registered_tool,
            CapabilityTarget.AGENT_STATE.value: self._execute_registered_tool,
            CapabilityTarget.ROBOT_GATEWAY.value: self._execute_registered_tool,
            CapabilityTarget.REMOTE_SERVICE.value: HttpRemoteServiceExecutor(),
        }

    def register_target(
        self,
        target: CapabilityTarget | str,
        handler: ExecutionTargetHandler,
    ) -> None:
        target_name = target.value if isinstance(target, CapabilityTarget) else str(target)
        if not target_name.strip():
            raise ValueError("execution target cannot be empty")
        self._target_handlers[target_name] = handler

    def dispatch(self, request: ExecutionRequest) -> ExecutionEvent:
        try:
            capability = self.capability_registry.get_by_name(request.capability)
            expected_target = capability.execution_target.value
            if request.execution_target != expected_target:
                raise ValueError(
                    f"Capability {request.capability} requires target {expected_target}, "
                    f"not {request.execution_target}"
                )
            try:
                target_handler = self._target_handlers[request.execution_target]
            except KeyError as exc:
                raise ValueError(
                    f"No execution handler registered for target: {request.execution_target}"
                ) from exc
            result = target_handler(request, capability)
            if isinstance(result, ExecutionEvent):
                return self._validate_target_event(request, capability, result)
            return request.event(
                ExecutionStatus.SUCCEEDED,
                result=result,
                metadata={"tool": capability.tool_name},
            )
        except Exception as exc:
            return request.event(
                ExecutionStatus.FAILED,
                result=f"ERROR: {type(exc).__name__}: {exc}",
                error=ExecutionError.from_exception(exc),
            )

    def _execute_registered_tool(
        self,
        request: ExecutionRequest,
        capability: CapabilitySpec,
    ) -> Any:
        check_tool_call(capability.tool_name, request.arguments)
        try:
            handler = self.handlers[capability.tool_name]
        except KeyError as exc:
            raise KeyError(f"No handler registered for tool: {capability.tool_name}") from exc
        return handler(**request.arguments)

    @staticmethod
    def _validate_target_event(
        request: ExecutionRequest,
        capability: CapabilitySpec,
        event: ExecutionEvent,
    ) -> ExecutionEvent:
        if event.execution_id != request.execution_id:
            raise ValueError("target event execution_id does not match request")
        if event.capability != request.capability:
            raise ValueError("target event capability does not match request")
        if event.execution_target != request.execution_target:
            raise ValueError("target event execution_target does not match request")
        result = event.result
        if event.status is ExecutionStatus.FAILED and result is None and event.error is not None:
            result = f"ERROR: {event.error.code}: {event.error.message}"
        return replace(
            event,
            result=result,
            metadata={**request.metadata, **event.metadata, "tool": capability.tool_name},
        )


DISPATCHER = ExecutionDispatcher()
