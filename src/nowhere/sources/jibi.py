from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

from .base import Observation, RawArtifact, SourceHealth, SourceRequest


class JibiInputAdapter:
    source_name = "jibi"
    rights_class = "internal_licensed"

    def __init__(self, input_path: Path) -> None:
        self.input_path = input_path

    def fetch(self, request: SourceRequest) -> RawArtifact:
        payload = self.input_path.read_text(encoding="utf-8")
        input_format = _detect_input_format(payload)
        return RawArtifact(
            source_id=request.source_id,
            captured_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            payload=payload,
            content_type="application/json" if input_format == "json" else "application/x-ndjson",
            rights_class=self.rights_class,
            raw_path=self.input_path,
            metadata={"adapter": self.source_name, "input_format": input_format},
        )

    def normalize(self, raw: RawArtifact) -> list[Observation]:
        observations: list[Observation] = []
        for index, item in enumerate(_load_events(raw.payload), start=1):
            event_id = str(item.get("event_id") or item.get("id") or item.get("candidate_id") or f"jibi-event-{index:04d}")
            normalized = _normalize_event(item, raw.source_id)
            observations.append(
                Observation(
                    observation_id=event_id,
                    source_id=raw.source_id,
                    field_name="news_event",
                    value=normalized,
                    unit=None,
                    as_of=str(normalized.get("first_seen_at") or raw.captured_at),
                    quality_flags=_quality_flags(normalized),
                    rights_class=raw.rights_class,
                )
            )
        return observations

    def healthcheck(self) -> SourceHealth:
        if not self.input_path.exists():
            return SourceHealth("jibi", "blocked", f"missing input file: {self.input_path}")
        return SourceHealth("jibi", "ok", str(self.input_path))


JibiJsonlAdapter = JibiInputAdapter


def _detect_input_format(payload: str) -> str:
    stripped = payload.lstrip()
    return "json" if stripped.startswith("{") or stripped.startswith("[") else "jsonl"


def _load_events(payload: str) -> list[dict[str, object]]:
    stripped = payload.lstrip()
    if not stripped:
        return []
    if stripped.startswith("[") or stripped.startswith("{"):
        parsed = json.loads(payload)
        return _events_from_json(parsed)

    events: list[dict[str, object]] = []
    for line in payload.splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        if isinstance(item, dict):
            events.append(item)
    return events


def _events_from_json(value: object) -> list[dict[str, object]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if not isinstance(value, dict):
        return []
    for key in ("events", "items", "candidates", "articles", "results", "data"):
        nested = value.get(key)
        if isinstance(nested, list):
            return [item for item in nested if isinstance(item, dict)]
    return [value]


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
    raw_source_ids = item.get("source_ids") or item.get("sources") or item.get("source") or item.get("outlet") or [fallback_source_id]
    source_ids = _string_list(raw_source_ids) or [fallback_source_id]

    title = str(item.get("title") or item.get("headline") or item.get("summary") or item.get("body") or "Untitled jibi event")
    normalized = dict(item)
    normalized["title"] = title
    normalized["source_ids"] = source_ids
    normalized["category"] = str(item.get("category") or item.get("section") or item.get("topic") or "jibi")
    normalized["status"] = _normalize_status(item.get("status"))
    normalized["significance_hint"] = _normalize_significance(item.get("significance_hint") or item.get("score") or item.get("materiality"))
    normalized["entities"] = _string_list(item.get("entities") or item.get("companies") or item.get("keywords"))
    normalized["tickers"] = _string_list(item.get("tickers") or item.get("symbols"))
    normalized["market_links"] = _string_list(item.get("market_links") or item.get("market_connection") or item.get("market_connections"))
    normalized["open_questions"] = _string_list(item.get("open_questions"))
    normalized["first_seen_at"] = item.get("first_seen_at") or item.get("published_at") or item.get("created_at")
    if item.get("url") and "url" not in normalized:
        normalized["url"] = item["url"]
    if not normalized.get("reported_claims") and normalized.get("facts"):
        facts = normalized["facts"]
        if isinstance(facts, list):
            normalized["reported_claims"] = [
                str(fact.get("text", fact)) if isinstance(fact, dict) else str(fact)
                for fact in facts
            ]
    if not normalized.get("reported_claims") and item.get("summary"):
        normalized["reported_claims"] = [str(item["summary"])]
    normalized.setdefault("reported_claims", [])
    return normalized


def _normalize_status(value: object) -> str:
    if value in {"confirmed", "partially_confirmed", "unverified"}:
        return str(value)
    if value in {"verified", "published", "ready"}:
        return "confirmed"
    if value in {"draft", "candidate", "needs_review"}:
        return "partially_confirmed"
    return "unverified"


def _normalize_significance(value: object) -> float:
    if isinstance(value, bool):
        return 0.1
    if isinstance(value, (int, float)):
        if value > 1:
            return max(0.0, min(1.0, float(value) / 100.0))
        return max(0.0, min(1.0, float(value)))
    return 0.1


def _string_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, list):
        result = []
        for item in value:
            if isinstance(item, dict):
                text = item.get("text") or item.get("name") or item.get("title") or item.get("symbol")
            else:
                text = item
            if text:
                result.append(str(text))
        return result
    return [str(value)]
