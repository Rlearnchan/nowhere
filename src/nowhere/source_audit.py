from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

RESTRICTED_RIGHTS = {"public_web_restricted"}
WARNING_FLAGS = {
    "prototype_only",
    "redistribution_restricted",
    "yahoo_terms_review_required",
    "missing_source_ids",
    "missing_market_links",
    "missing_reported_claims",
    "low_significance_hint",
    "unverified_news_event",
    "single_point_window",
    "zero_window_start_price",
    "market_data_stale",
    "unparseable_market_timestamp",
}
NEWS_REVIEW_FLAGS = {"missing_market_links", "missing_reported_claims", "low_significance_hint", "unverified_news_event"}
GLOBAL_PRICE_REVIEW_FLAGS = {"yahoo_terms_review_required", "single_point_window", "zero_window_start_price", "market_data_stale", "unparseable_market_timestamp"}


def audit_adapter_outputs(
    adapter_output_dir: Path,
    now: datetime | None = None,
    stale_hours: int = 24,
) -> dict[str, Any]:
    adapter_output_dir = adapter_output_dir.resolve()
    observations_path = adapter_output_dir / "observations" / "observations.json"
    observations = _load_json_list(observations_path)
    manifest = _load_json_object(adapter_output_dir / "manifest.json")
    now = now or datetime.now(timezone.utc)

    stale: list[dict[str, Any]] = []
    restricted: list[dict[str, Any]] = []
    flagged: list[dict[str, Any]] = []
    news_flagged: list[dict[str, Any]] = []
    global_price_flagged: list[dict[str, Any]] = []
    naver_prototype: list[dict[str, Any]] = []
    source_counts: dict[str, int] = {}
    field_counts: dict[str, int] = {}

    for obs in observations:
        source_id = str(obs.get("source_id", "unknown"))
        field_name = str(obs.get("field_name", "unknown"))
        source_counts[source_id] = source_counts.get(source_id, 0) + 1
        field_counts[field_name] = field_counts.get(field_name, 0) + 1

        age = _age_hours(obs.get("as_of"), now)
        if age is None:
            stale.append(_issue(obs, "missing_or_unparseable_as_of", None))
        elif age > stale_hours:
            stale.append(_issue(obs, "stale_observation", round(age, 2)))

        if obs.get("rights_class") in RESTRICTED_RIGHTS:
            item = _issue(obs, "restricted_rights", age)
            restricted.append(item)
            if field_name == "index_snapshot" and str(source_id).startswith("src-naver"):
                naver_prototype.append(item)

        flags = [str(flag) for flag in obs.get("quality_flags", [])]
        warning_flags = sorted(set(flags).intersection(WARNING_FLAGS))
        if warning_flags:
            item = _issue(obs, "quality_flags", age)
            item["quality_flags"] = warning_flags
            flagged.append(item)
            if field_name == "news_event" and set(warning_flags).intersection(NEWS_REVIEW_FLAGS):
                news_flagged.append(item)
            if field_name == "global_price_latest" and set(warning_flags).intersection(GLOBAL_PRICE_REVIEW_FLAGS):
                global_price_flagged.append(item)

    coverage = _coverage_summary(field_counts, manifest)

    blockers: list[str] = []
    warnings: list[str] = []
    if coverage["missing_required_fields"]:
        blockers.append(f"missing required adapter fields: {', '.join(coverage['missing_required_fields'])}")
    if stale:
        warnings.append(f"{len(stale)} stale or undated observations")
    if restricted:
        warnings.append(f"{len(restricted)} observations have restricted rights")
    if naver_prototype:
        warnings.append(f"{len(naver_prototype)} Naver prototype snapshots are review-only and not redistributable")
    if flagged:
        warnings.append(f"{len(flagged)} observations carry quality warning flags")
    if news_flagged:
        warnings.append(f"{len(news_flagged)} news events need editorial review")
    if global_price_flagged:
        warnings.append(f"{len(global_price_flagged)} global price observations need market data review")
    if any("market_data_stale" in item.get("quality_flags", []) for item in global_price_flagged):
        warnings.append("global context market data is stale")

    result = {
        "schema_version": "nowhere.source_audit.v1",
        "adapter_output_dir": str(adapter_output_dir),
        "generated_at": now.isoformat(timespec="seconds"),
        "stale_hours": stale_hours,
        "status": "blocked" if blockers else ("review_needed" if warnings else "ok"),
        "blockers": blockers,
        "warnings": warnings,
        "summary": {
            "observation_count": len(observations),
            "source_counts": source_counts,
            "field_counts": field_counts,
            "stale_count": len(stale),
            "restricted_rights_count": len(restricted),
            "naver_prototype_count": len(naver_prototype),
            "quality_flagged_count": len(flagged),
            "news_event_review_count": len(news_flagged),
            "global_price_review_count": len(global_price_flagged),
            "coverage": coverage,
        },
        "stale_observations": stale,
        "restricted_rights": restricted,
        "naver_prototype_snapshots": naver_prototype,
        "quality_flags": flagged,
        "news_event_review_flags": news_flagged,
        "global_price_review_flags": global_price_flagged,
    }
    output_path = adapter_output_dir / "source_audit.json"
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def _coverage_summary(field_counts: dict[str, int], manifest: dict[str, Any]) -> dict[str, Any]:
    contract = manifest.get("adapter_contract", {}) if isinstance(manifest, dict) else {}
    required_fields = contract.get("required_fields", []) if isinstance(contract, dict) else []
    required = [str(item) for item in required_fields if isinstance(item, str)]
    missing = [field for field in required if field_counts.get(field, 0) < 1]
    return {
        "required_fields": required,
        "present_fields": sorted(field_counts.keys()),
        "missing_required_fields": missing,
        "valid": not missing,
    }


def _issue(obs: dict[str, Any], reason: str, age_hours: float | None) -> dict[str, Any]:
    return {
        "reason": reason,
        "observation_id": obs.get("observation_id"),
        "source_id": obs.get("source_id"),
        "field_name": obs.get("field_name"),
        "as_of": obs.get("as_of"),
        "age_hours": round(age_hours, 2) if isinstance(age_hours, float) else age_hours,
        "rights_class": obs.get("rights_class"),
    }


def _age_hours(value: Any, now: datetime) -> float | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return max(0.0, (now - parsed.astimezone(timezone.utc)).total_seconds() / 3600)


def _load_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _load_json_list(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]
