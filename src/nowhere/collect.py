from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from .contracts import load_json, validate_contract
from .sources.base import Observation, RawArtifact, SourceRequest
from .sources.jibi import JibiJsonlAdapter
from .sources.krx_adapter import KrxIndexAdapter
from .sources.naver_snapshot import NaverSnapshotAdapter
from .sources.yfinance_adapter import YFinanceAdapter
from .source_audit import audit_adapter_outputs


def collect_fixture_sources(
    repo_root: Path,
    run_id: str,
    output_root: Path | None = None,
    jibi_path: Path | None = None,
    naver_paths: list[Path] | None = None,
    yfinance_path: Path | None = None,
    live_yfinance: bool = False,
    yfinance_tickers: list[str] | None = None,
    naver_urls: list[str] | None = None,
    live_krx: bool = False,
    krx_auth_key: str | None = None,
    krx_bas_dd: str | None = None,
    krx_markets: list[str] | None = None,
    krx_lookback_days: int = 10,
) -> Path:
    repo_root = repo_root.resolve()
    output_root = (output_root or repo_root / "runs").resolve()
    run_dir = output_root / run_id
    out_dir = run_dir / "adapter_outputs"
    raw_dir = out_dir / "raw"
    obs_dir = out_dir / "observations"
    raw_dir.mkdir(parents=True, exist_ok=True)
    obs_dir.mkdir(parents=True, exist_ok=True)

    jibi_path = (jibi_path or repo_root / "fixtures/jibi/sample_events.jsonl").resolve()
    naver_paths = naver_paths or [repo_root / "fixtures/naver/kospi_snapshot.json", repo_root / "fixtures/naver/kosdaq_snapshot.json"]
    yfinance_path = (yfinance_path or repo_root / "fixtures/yfinance/global_prices.json").resolve()

    raw_artifacts: list[RawArtifact] = []
    observations: list[Observation] = []

    jibi = JibiJsonlAdapter(jibi_path)
    raw, obs = _run_adapter(jibi, SourceRequest("src-jibi-fixture"))
    raw_artifacts.append(raw)
    observations.extend(obs)

    if live_krx:
        from .env import load_env

        env = load_env()
        auth_key = krx_auth_key or env.get("KRX_AUTH_KEY")
        for market in (krx_markets or ["KOSPI", "KOSDAQ"]):
            adapter = KrxIndexAdapter(auth_key=auth_key, market=market)
            raw, obs = _run_adapter(
                adapter,
                SourceRequest(
                    f"src-krx-{market.lower()}",
                    {"market": market, "bas_dd": krx_bas_dd or "", "lookback_days": krx_lookback_days},
                ),
            )
            raw_artifacts.append(raw)
            observations.extend(obs)
    elif naver_urls:
        for idx, url in enumerate(naver_urls, start=1):
            adapter = NaverSnapshotAdapter(url=url)
            raw, obs = _run_adapter(adapter, SourceRequest(f"src-naver-live-{idx}"))
            raw_artifacts.append(raw)
            observations.extend(obs)
    else:
        for idx, path in enumerate(naver_paths, start=1):
            adapter = NaverSnapshotAdapter(path.resolve())
            raw, obs = _run_adapter(adapter, SourceRequest(f"src-naver-fixture-{idx}"))
            raw_artifacts.append(raw)
            observations.extend(obs)

    yfinance = YFinanceAdapter()
    if live_yfinance:
        raw, obs = _run_adapter(
            yfinance,
            SourceRequest(
                "src-yfinance-live",
                {"tickers": yfinance_tickers or ["SPY", "QQQ"], "period": "5d", "interval": "1d"},
            ),
        )
        raw_artifacts.append(raw)
        observations.extend(obs)
    else:
        yfinance_payload = yfinance_path.read_text(encoding="utf-8")
        yfinance_raw = RawArtifact(
            source_id="src-yfinance-fixture",
            captured_at=_utc_now(),
            payload=yfinance_payload,
            content_type="application/json",
            rights_class="open_source_adapter",
            raw_path=yfinance_path,
            metadata={"adapter": "yfinance", "fixture": True},
        )
        raw_artifacts.append(yfinance_raw)
        observations.extend(yfinance.normalize(yfinance_raw))

    for raw in raw_artifacts:
        (raw_dir / f"{raw.source_id}.txt").write_text(raw.payload, encoding="utf-8")
    _write_json(obs_dir / "observations.json", [_observation_dict(item) for item in observations])

    market_pack = build_market_pack_from_observations(run_id, observations, raw_artifacts)
    news_pack = build_news_pack_from_observations(run_id, observations, raw_artifacts)
    _write_json(out_dir / "market_pack.json", market_pack)
    _write_json(out_dir / "news_pack.json", news_pack)

    validation = {
        "market_pack": [issue.__dict__ for issue in validate_contract(market_pack, load_json(repo_root / "contracts/market_pack.schema.json"))],
        "news_pack": [issue.__dict__ for issue in validate_contract(news_pack, load_json(repo_root / "contracts/news_pack.schema.json"))],
    }
    _write_json(out_dir / "validation.json", validation)
    manifest = {
        "run_id": run_id,
        "generated_at": _utc_now(),
        "raw_count": len(raw_artifacts),
        "observation_count": len(observations),
        "adapter_contract": {
            "schema_version": "nowhere.adapter_contract.v1",
            "required_fields": ["news_event", "index_snapshot", "global_price_latest"],
            "required_adapters": ["jibi", "krx_or_naver_index_snapshot", "yfinance"],
            "rights_policy": {
                "public_web_restricted": "review_only_not_redistributable",
                "open_source_adapter": "terms_review_required",
                "internal_licensed": "internal_use_allowed",
                "public_official": "official_api_terms_review",
            },
            "source_profiles": _source_profiles(raw_artifacts),
        },
    }
    _write_json(out_dir / "manifest.json", manifest)
    audit_adapter_outputs(out_dir)
    return out_dir


def build_market_pack_from_observations(run_id: str, observations: list[Observation], raw_artifacts: list[RawArtifact]) -> dict[str, Any]:
    index_items = [obs for obs in observations if obs.field_name == "index_snapshot"]
    global_items = [obs for obs in observations if obs.field_name == "global_price_latest"]
    market_as_of = max((obs.as_of for obs in index_items), default=_utc_now())
    trade_date = market_as_of[:10]
    return {
        "schema_version": "market_pack.v1",
        "run": {
            "run_id": run_id,
            "trade_date": trade_date,
            "generated_at": _utc_now(),
            "market_as_of": market_as_of,
            "quality_status": "review_needed",
            "warnings": _market_warnings(index_items, global_items),
        },
        "indices": [_index_from_observation(obs) for obs in index_items],
        "breadth": [],
        "flows": [],
        "fx": [],
        "global_context": [_global_from_observation(obs) for obs in global_items],
        "movers": [],
        "observations": [
            {
                "observation_id": "collector-warning-01",
                "text": "Collector-generated pack is a draft assembled from fixtures and requires human review.",
                "evidence_ids": [obs.observation_id for obs in index_items[:1]] or ["collector-fixture"],
                "observation_type": "data_warning",
            }
        ],
        "sources": _market_sources(raw_artifacts),
    }


def build_news_pack_from_observations(run_id: str, observations: list[Observation], raw_artifacts: list[RawArtifact]) -> dict[str, Any]:
    events = []
    for obs in observations:
        if obs.field_name != "news_event" or not isinstance(obs.value, dict):
            continue
        source_ids = obs.value.get("source_ids") or [obs.source_id]
        events.append(
            {
                "event_id": obs.observation_id,
                "first_seen_at": obs.as_of,
                "title": str(obs.value.get("title", obs.observation_id)),
                "category": str(obs.value.get("category", "fixture_news")),
                "entities": obs.value.get("entities", []),
                "tickers": obs.value.get("tickers", []),
                "facts": [
                    {
                        "fact_id": f"{obs.observation_id}-fact-01",
                        "text": str(obs.value.get("title", obs.observation_id)),
                        "source_ids": source_ids,
                    }
                ],
                "reported_claims": obs.value.get("reported_claims", []),
                "sources": source_ids,
                "market_links": obs.value.get("market_links", []),
                "status": obs.value.get("status", "unverified"),
                "significance_hint": obs.value.get("significance_hint", 0.1),
                "open_questions": obs.value.get("open_questions", []),
                "quality_flags": obs.quality_flags,
                "rights_class": obs.rights_class,
            }
        )
    return {
        "schema_version": "news_pack.v1",
        "run_id": run_id,
        "news_cutoff": max((event["first_seen_at"] for event in events), default=_utc_now()),
        "events": events,
        "sources": _news_sources(raw_artifacts),
    }


def _run_adapter(adapter: Any, request: SourceRequest) -> tuple[RawArtifact, list[Observation]]:
    raw = adapter.fetch(request)
    return raw, adapter.normalize(raw)


def _index_from_observation(obs: Observation) -> dict[str, Any]:
    value = obs.value
    if not isinstance(value, dict):
        raise TypeError("index snapshot observation value must be an object")
    return {
        "evidence_id": str(value.get("evidence_id", obs.observation_id)),
        "symbol": str(value["symbol"]),
        "name": str(value.get("name", value["symbol"])),
        "last": float(value["last"]),
        "change": float(value["change"]),
        "change_pct": float(value["change_pct"]),
        "prev_close": float(value["prev_close"]),
        "open": float(value["open"]),
        "high": float(value["high"]),
        "low": float(value["low"]),
        "as_of": obs.as_of,
        "source_id": obs.source_id,
        "rights_class": obs.rights_class,
        "prototype_only": "prototype_only" in obs.quality_flags,
        "redistribution_allowed": obs.rights_class != "public_web_restricted" and "redistribution_restricted" not in obs.quality_flags,
        "quality_flags": obs.quality_flags,
    }


def _global_from_observation(obs: Observation) -> dict[str, Any]:
    value = obs.value if isinstance(obs.value, dict) else {}
    symbol = str(value.get("symbol", obs.observation_id))
    result = {
        "evidence_id": obs.observation_id,
        "symbol": symbol,
        "name": f"{symbol} latest",
        "value": float(value.get("close", 0)),
        "unit": obs.unit or "price",
        "as_of": obs.as_of,
        "source_id": obs.source_id,
        "rights_class": obs.rights_class,
        "quality_flags": obs.quality_flags,
    }
    if value.get("change_pct_from_window_start") is not None:
        result["change_pct"] = float(value["change_pct_from_window_start"])
    for key in ("window_start", "window_end", "point_count", "period", "interval", "freshness_age_hours", "stale_hours"):
        if value.get(key) is not None:
            result[key] = value[key]
    return result


def _market_sources(raw_artifacts: list[RawArtifact]) -> list[dict[str, Any]]:
    sources = []
    for raw in raw_artifacts:
        if raw.source_id.startswith("src-jibi"):
            continue
        sources.append(
            {
                "source_id": raw.source_id,
                "name": str(raw.metadata.get("adapter", raw.source_id)),
                "url": _artifact_url(raw),
                "retrieved_at": raw.captured_at,
                "rights_class": raw.rights_class,
                "note": _source_note(raw),
            }
        )
    return sources


def _news_sources(raw_artifacts: list[RawArtifact]) -> list[dict[str, Any]]:
    result = []
    for raw in raw_artifacts:
        if not raw.source_id.startswith("src-jibi"):
            continue
        result.append(
            {
                "source_id": raw.source_id,
                "name": "jibi fixture input",
                "url": _artifact_url(raw),
                "published_at": raw.captured_at,
                "rights_class": raw.rights_class,
            }
        )
    return result


def _source_profiles(raw_artifacts: list[RawArtifact]) -> list[dict[str, Any]]:
    profiles = []
    for raw in raw_artifacts:
        adapter = str(raw.metadata.get("adapter", raw.source_id))
        profile = {
            "source_id": raw.source_id,
            "adapter": adapter,
            "rights_class": raw.rights_class,
            "retrieved_at": raw.captured_at,
            "role": _source_role(raw),
            "public_note": _public_source_note(raw),
        }
        if raw.metadata.get("bas_dd_resolved"):
            profile["resolved_trade_date"] = raw.metadata["bas_dd_resolved"]
        if raw.metadata.get("attempted_bas_dds"):
            profile["attempted_trade_dates"] = raw.metadata["attempted_bas_dds"]
        profiles.append(profile)
    return profiles


def _source_role(raw: RawArtifact) -> str:
    adapter = raw.metadata.get("adapter")
    if adapter == "jibi":
        return "news"
    if adapter == "yfinance":
        return "global_market_context"
    if adapter == "krx_openapi":
        return "korea_market_index"
    if adapter == "naver_finance_snapshot":
        return "prototype_market_index"
    return "supporting_data"


def _public_source_note(raw: RawArtifact) -> str:
    adapter = raw.metadata.get("adapter")
    if adapter == "krx_openapi":
        return "Official KRX index snapshot; publication terms still require review."
    if adapter == "yfinance":
        return "Global market context from Yahoo Finance via yfinance; use as supporting context."
    if adapter == "jibi":
        return "Licensed news input normalized through jibi."
    if adapter == "naver_finance_snapshot":
        return "Prototype fallback snapshot; not for public redistribution."
    return "Collected source adapter output."


def _artifact_url(raw: RawArtifact) -> str:
    if raw.raw_path:
        return f"urn:local-fixture:{raw.raw_path.name}"
    return f"urn:adapter:{raw.source_id}"


def _source_note(raw: RawArtifact) -> str:
    flags = []
    if raw.metadata.get("prototype_only"):
        flags.append("prototype_only")
    if raw.metadata.get("redistribution_warning"):
        flags.append("redistribution_warning")
    if raw.metadata.get("fixture"):
        flags.append("fixture")
    if raw.metadata.get("adapter") == "krx_openapi":
        flags.append("official_api_terms_review")
    return ", ".join(flags) if flags else "fixture adapter output"


def _market_warnings(index_items: list[Observation], global_items: list[Observation]) -> list[str]:
    warnings = ["collector output; review before publication"]
    if any(obs.source_id.startswith("src-naver") for obs in index_items):
        warnings.append("Naver snapshots are prototype_only and redistribution restricted")
    if any(obs.source_id.startswith("src-krx") for obs in index_items):
        warnings.append("KRX official API values require terms and redistribution review")
    if global_items:
        warnings.append("yfinance values require Yahoo terms review")
    if any("market_data_stale" in obs.quality_flags for obs in global_items):
        warnings.append("global context prices are stale relative to collection time")
    return warnings


def _observation_dict(obs: Observation) -> dict[str, Any]:
    return asdict(obs)


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
