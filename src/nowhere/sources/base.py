from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class SourceRequest:
    source_id: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RawArtifact:
    source_id: str
    captured_at: str
    payload: str
    content_type: str
    rights_class: str
    raw_path: Path | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Observation:
    observation_id: str
    source_id: str
    field_name: str
    value: Any
    unit: str | None
    as_of: str
    quality_flags: list[str] = field(default_factory=list)
    rights_class: str = "internal_derived"


@dataclass(frozen=True)
class SourceHealth:
    source_id: str
    status: str
    message: str = ""


class SourceAdapter(Protocol):
    source_name: str
    rights_class: str

    def fetch(self, request: SourceRequest) -> RawArtifact: ...
    def normalize(self, raw: RawArtifact) -> list[Observation]: ...
    def healthcheck(self) -> SourceHealth: ...
