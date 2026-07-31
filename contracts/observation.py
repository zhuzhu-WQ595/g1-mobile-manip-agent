from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


@dataclass(frozen=True)
class Observation:
    """Structured evidence returned by perception services."""

    source: str
    path_clear: bool | None = None
    objects: tuple[dict[str, Any], ...] = ()
    obstacles: tuple[dict[str, Any], ...] = ()
    confidence: float | None = None
    image_reference: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    observation_id: str = field(default_factory=lambda: f"obs_{uuid4().hex}")
    captured_at: str = field(default_factory=_utc_now)

    def __post_init__(self) -> None:
        if not self.source.strip():
            raise ValueError("observation source cannot be empty")
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ValueError("observation confidence must be between 0 and 1")

    def to_dict(self) -> dict[str, Any]:
        return {
            "observation_id": self.observation_id,
            "source": self.source,
            "captured_at": self.captured_at,
            "path_clear": self.path_clear,
            "objects": list(self.objects),
            "obstacles": list(self.obstacles),
            "confidence": self.confidence,
            "image_reference": self.image_reference,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Observation:
        objects = data.get("objects", [])
        obstacles = data.get("obstacles", [])
        metadata = data.get("metadata", {})
        if not isinstance(objects, list) or not all(isinstance(item, dict) for item in objects):
            raise ValueError("observation objects must be a list of objects")
        if not isinstance(obstacles, list) or not all(isinstance(item, dict) for item in obstacles):
            raise ValueError("observation obstacles must be a list of objects")
        return cls(
            observation_id=str(data.get("observation_id") or f"obs_{uuid4().hex}"),
            source=str(data.get("source", "")),
            captured_at=str(data.get("captured_at") or _utc_now()),
            path_clear=data.get("path_clear") if isinstance(data.get("path_clear"), bool) else None,
            objects=tuple(objects),
            obstacles=tuple(obstacles),
            confidence=float(data["confidence"]) if data.get("confidence") is not None else None,
            image_reference=(
                str(data["image_reference"]) if data.get("image_reference") is not None else None
            ),
            metadata=metadata if isinstance(metadata, dict) else {"value": metadata},
        )
