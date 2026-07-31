from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4


class ExecutionStatus(str, Enum):
    CREATED = "created"
    ACCEPTED = "accepted"
    RUNNING = "running"
    WAITING_FEEDBACK = "waiting_feedback"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


def normalize_execution_status(value: ExecutionStatus | str) -> ExecutionStatus:
    if isinstance(value, ExecutionStatus):
        return value
    aliases = {
        "ok": ExecutionStatus.SUCCEEDED,
        "error": ExecutionStatus.FAILED,
        "pending": ExecutionStatus.ACCEPTED,
        "completed": ExecutionStatus.SUCCEEDED,
    }
    normalized = str(value).strip().lower()
    if normalized in aliases:
        return aliases[normalized]
    return ExecutionStatus(normalized)


TERMINAL_EXECUTION_STATUSES = frozenset(
    {
        ExecutionStatus.SUCCEEDED,
        ExecutionStatus.FAILED,
        ExecutionStatus.CANCELLED,
        ExecutionStatus.TIMED_OUT,
    }
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


@dataclass(frozen=True)
class ExecutionError:
    code: str
    message: str
    retryable: bool = False
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "details": self.details,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExecutionError:
        details = data.get("details", {})
        return cls(
            code=str(data.get("code", "execution_error")),
            message=str(data.get("message", "execution failed")),
            retryable=bool(data.get("retryable", False)),
            details=details if isinstance(details, dict) else {"value": details},
        )

    @classmethod
    def from_exception(cls, exc: Exception) -> ExecutionError:
        return cls(
            code=type(exc).__name__,
            message=str(exc),
            retryable=not isinstance(exc, (PermissionError, ValueError, KeyError)),
        )


@dataclass(frozen=True)
class ExecutionRequest:
    capability: str
    execution_target: str
    arguments: dict[str, Any] = field(default_factory=dict)
    execution_id: str = field(default_factory=lambda: f"exec_{uuid4().hex}")
    timeout_s: float = 30.0
    created_at: str = field(default_factory=utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.capability.strip():
            raise ValueError("execution capability cannot be empty")
        if not self.execution_target.strip():
            raise ValueError("execution target cannot be empty")
        if self.timeout_s <= 0:
            raise ValueError("execution timeout_s must be greater than 0")

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "capability": self.capability,
            "execution_target": self.execution_target,
            "arguments": self.arguments,
            "timeout_s": self.timeout_s,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExecutionRequest:
        arguments = data.get("arguments", {})
        metadata = data.get("metadata", {})
        return cls(
            execution_id=str(data.get("execution_id") or f"exec_{uuid4().hex}"),
            capability=str(data.get("capability", "")),
            execution_target=str(data.get("execution_target", "")),
            arguments=arguments if isinstance(arguments, dict) else {},
            timeout_s=float(data.get("timeout_s", 30.0)),
            created_at=str(data.get("created_at") or utc_now()),
            metadata=metadata if isinstance(metadata, dict) else {},
        )

    def event(
        self,
        status: ExecutionStatus,
        *,
        progress: float | None = None,
        result: Any = None,
        error: ExecutionError | None = None,
        observation: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ExecutionEvent:
        return ExecutionEvent(
            execution_id=self.execution_id,
            capability=self.capability,
            execution_target=self.execution_target,
            status=status,
            progress=progress,
            result=result,
            error=error,
            observation=observation,
            metadata={**self.metadata, **(metadata or {})},
        )


@dataclass(frozen=True)
class ExecutionEvent:
    execution_id: str
    capability: str
    execution_target: str
    status: ExecutionStatus
    occurred_at: str = field(default_factory=utc_now)
    progress: float | None = None
    result: Any = None
    error: ExecutionError | None = None
    observation: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.execution_id.strip():
            raise ValueError("execution event id cannot be empty")
        if self.progress is not None and not 0.0 <= self.progress <= 1.0:
            raise ValueError("execution progress must be between 0 and 1")
        if self.status is ExecutionStatus.FAILED and self.error is None:
            raise ValueError("failed execution events require an error")

    @property
    def terminal(self) -> bool:
        return self.status in TERMINAL_EXECUTION_STATUSES

    @property
    def succeeded(self) -> bool:
        return self.status is ExecutionStatus.SUCCEEDED

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "capability": self.capability,
            "execution_target": self.execution_target,
            "status": self.status.value,
            "occurred_at": self.occurred_at,
            "progress": self.progress,
            "result": self.result,
            "error": self.error.to_dict() if self.error is not None else None,
            "observation": self.observation,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExecutionEvent:
        raw_error = data.get("error")
        observation = data.get("observation")
        metadata = data.get("metadata", {})
        return cls(
            execution_id=str(data.get("execution_id", "")),
            capability=str(data.get("capability", "")),
            execution_target=str(data.get("execution_target", "")),
            status=normalize_execution_status(str(data.get("status", "created"))),
            occurred_at=str(data.get("occurred_at") or utc_now()),
            progress=float(data["progress"]) if data.get("progress") is not None else None,
            result=data.get("result"),
            error=ExecutionError.from_dict(raw_error) if isinstance(raw_error, dict) else None,
            observation=observation if isinstance(observation, dict) else None,
            metadata=metadata if isinstance(metadata, dict) else {},
        )


@dataclass(frozen=True)
class ExecutionResult:
    execution_id: str
    capability: str
    status: ExecutionStatus
    result: Any = None
    error: ExecutionError | None = None
    completed_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if self.status not in TERMINAL_EXECUTION_STATUSES:
            raise ValueError("execution results require a terminal status")

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "capability": self.capability,
            "status": self.status.value,
            "result": self.result,
            "error": self.error.to_dict() if self.error is not None else None,
            "completed_at": self.completed_at,
        }

    @classmethod
    def from_event(cls, event: ExecutionEvent) -> ExecutionResult:
        if not event.terminal:
            raise ValueError("cannot create an execution result from a non-terminal event")
        return cls(
            execution_id=event.execution_id,
            capability=event.capability,
            status=event.status,
            result=event.result,
            error=event.error,
            completed_at=event.occurred_at,
        )
