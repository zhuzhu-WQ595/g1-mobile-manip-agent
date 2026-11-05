from __future__ import annotations

from dataclasses import dataclass

from contracts.capability import CapabilitySpec
from contracts.resource import ExecutionResource, ResourceStatus

from .resources import RESOURCE_REGISTRY, ResourceRegistry


ELIGIBLE_STATUSES = frozenset({ResourceStatus.AVAILABLE, ResourceStatus.DEGRADED})
STATUS_RANK = {
    ResourceStatus.AVAILABLE: 0,
    ResourceStatus.DEGRADED: 1,
}


@dataclass(frozen=True)
class ResourceSelection:
    resource: ExecutionResource
    reason: str


class ResourceSelector:
    def __init__(self, registry: ResourceRegistry = RESOURCE_REGISTRY) -> None:
        self.registry = registry

    def select(
        self,
        capability: CapabilitySpec,
        requested_resource_id: str | None = None,
    ) -> ResourceSelection:
        self.registry.refresh_stale()
        if requested_resource_id:
            resource = self.registry.get(requested_resource_id)
            self._validate(resource, capability)
            return ResourceSelection(resource, "explicit resource requested")

        candidates = [
            resource
            for resource in self.registry.candidates(
                capability.name,
                capability.execution_target.value,
            )
            if resource.status in ELIGIBLE_STATUSES
        ]
        if not candidates:
            raise RuntimeError(
                f"No available execution resource for capability: {capability.name}"
            )
        resource = min(
            candidates,
            key=lambda item: (
                STATUS_RANK[item.status],
                item.load,
                -item.priority,
                item.resource_id,
            ),
        )
        reason = (
            f"automatic selection: status={resource.status.value}, "
            f"load={resource.load:.2f}, priority={resource.priority}"
        )
        return ResourceSelection(resource, reason)

    @staticmethod
    def _validate(resource: ExecutionResource, capability: CapabilitySpec) -> None:
        if not resource.supports(capability.name, capability.execution_target.value):
            raise ValueError(
                f"Resource {resource.resource_id} does not support capability {capability.name}"
            )
        if resource.status not in ELIGIBLE_STATUSES:
            raise RuntimeError(
                f"Execution resource {resource.resource_id} is {resource.status.value}"
            )
