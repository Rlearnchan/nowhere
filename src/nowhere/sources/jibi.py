from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

from .base import Observation, RawArtifact, SourceHealth, SourceRequest


class JibiJsonlAdapter:
    source_name = "jibi"
    rights_class = "internal_licensed"

    def __init__(self, input_path: Path) -> None:
        self.input_path = input_path

    def fetch(self, request: SourceRequest) -> RawArtifact:
        payload = self.input_path.read_text(encoding="utf-8")
        return RawArtifact(
            source_id=request.source_id,
            captured_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            payload=payload,
            content_type="application/x-ndjson",
            rights_class=self.rights_class,
            raw_path=self.input_path,
            metadata={"adapter": self.source_name},
        )

    def normalize(self, raw: RawArtifact) -> list[Observation]:
        observations: list[Observation] = []
        for index, line in enumerate(raw.payload.splitlines(), start=1):
            if not line.strip():
                continue
            item = json.loads(line)
            event_id = item.get("event_id") or f"jibi-event-{index:04d}"
            normalized = _normalize_event(item, raw.source_id)
            observations.append(
                Observation(
                    observation_id=event_id,
                    source_id=raw.source_id,
                    field_name="news_event",
                    value=normalized,
                    unit=None,
                    as_of=normalized.get("first_seen_at") or raw.captured_at,
                    quality_flags=_quality_flags(normalized),
                    rights_class=raw.rights_class,
                )
            )
        return observations

    def healthcheck(self) -> SourceHealth:
        if not self.input_path.exists():
            return SourceHealth("jibi", "blocked", f"missing input file: {self.input_path}")
        return SourceHealth("jibi", "ok", str(self.input_path))


def _quality_flags(item: dict[str, object]) -> list[str]:
    flags: list[str] = []
    if not item.get("source_ids") and not item.get("sources"):
        flags.append("missing_source_ids")
    if not item.get("market_links"):
        flags.append("missing_market_links")
    if not item.get("reported_claims") and not item.get("facts"):
        flags.append("missing_reported_claims")
    significance = item.get("significance_hint")
    if not isinstance(significance, (int, float)) or isinstance(significance, bool) or significance < 0.2:
        flags.append("low_significance_hint")
    if item.get("status") == "unverified":
        flags.append("unverified_news_event")
    return flags


def _normalize_event(item: dict[str, object], fallback_source_id: str) -> dict[str, object]:
    source_ids = item.get("source_ids") or item.get("sources") or [fallback_source_id]
    if isinstance(source_ids, str):
        source_ids = [source_ids]
    if not isinstance(source_ids, list):
        source_ids = [fallback_source_id]

    title = str(item.get("title") or item.get("headline") or item.get("summary") or "Untitled jibi event")
    normalized = dict(item)
    normalized["title"] = title
    normalized["source_ids"] = [str(source_id) for source_id in source_ids if source_id]
    normalized.setdefault("category", "jibi")
    normalized.setdefault("status", "unverified")
    normalized.setdefault("significance_hint", 0.1)
    normalized.setdefault("entities", [])
    normalized.setdefault("tickers", [])
    normalized.setdefault("market_links", [])
    normalized.setdefault("open_questions", [])
    if not normalized.get("reported_claims") and normalized.get("facts"):
        facts = normalized["facts"]
        if isinstance(facts, list):
            normalized["reported_claims"] = [
                str(fact.get("text", fact)) if isinstance(fact, dict) else str(fact)
                for fact in facts
            ]
    normalized.setdefault("reported_claims", [])
    return normalized
