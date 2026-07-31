from __future__ import annotations

from dataclasses import replace
from threading import RLock

from contracts.resource import ExecutionResource, ResourceStatus

from ..capabilities import CAPABILITY_REGISTRY, CapabilityRegistry


class ResourceRegistry:
    """Thread-safe runtime registry for concrete execution resources."""

    def __init__(self, resources: tuple[ExecutionResource, ...] | list[ExecutionResource] = ()) -> None:
        self._resources: dict[str, ExecutionResource] = {}
        self._lock = RLock()
        for resource in resources:
            self.register(resource)

    def register(self, resource: ExecutionResource) -> None:
        with self._lock:
            if resource.resource_id in self._resources:
                raise ValueError(f"Execution resource already registered: {resource.resource_id}")
            self._resources[resource.resource_id] = resource

    def unregister(self, resource_id: str) -> None:
        with self._lock:
            if resource_id not in self._resources:
                raise KeyError(f"Unknown execution resource: {resource_id}")
            del self._resources[resource_id]

    def get(self, resource_id: str) -> ExecutionResource:
        with self._lock:
            try:
                return self._resources[resource_id]
            except KeyError as exc:
                raise KeyError(f"Unknown execution resource: {resource_id}") from exc

    def all(self) -> tuple[ExecutionResource, ...]:
        with self._lock:
            return tuple(self._resources[key] for key in sorted(self._resources))

    def candidates(self, capability: str, execution_target: str) -> tuple[ExecutionResource, ...]:
        return tuple(
            resource
            for resource in self.all()
            if resource.supports(capability, execution_target)
        )

    def update_runtime(
        self,
        resource_id: str,
        *,
        status: ResourceStatus | None = None,
        load: float | None = None,
        priority: int | None = None,
    ) -> ExecutionResource:
        with self._lock:
            current = self.get(resource_id)
            updated = replace(
                current,
                status=status if status is not None else current.status,
                load=load if load is not None else current.load,
                priority=priority if priority is not None else current.priority,
            )
            self._resources[resource_id] = updated
            return updated


def build_default_resource_registry(
    capability_registry: CapabilityRegistry = CAPABILITY_REGISTRY,
) -> ResourceRegistry:
    by_target: dict[str, set[str]] = {}
    for capability in capability_registry.all():
        by_target.setdefault(capability.execution_target.value, set()).add(capability.name)
    resources = [
        ExecutionResource(
            resource_id=f"{target}.default",
            execution_target=target,
            capabilities=frozenset(capabilities),
            metadata={"kind": "built_in"},
        )
        for target, capabilities in sorted(by_target.items())
    ]
    return ResourceRegistry(resources)


RESOURCE_REGISTRY = build_default_resource_registry()
