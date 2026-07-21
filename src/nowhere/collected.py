from __future__ import annotations

import json
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from .contracts import load_json
from .phase0 import Phase0Result, build_fixture_bundle


def build_collected_bundle(
    repo_root: Path,
    adapter_output_dir: Path,
    run_id: str | None = None,
    output_root: Path | None = None,
    editorial_memo_path: Path | None = None,
    render_pdf: bool = True,
    editorial_mode: str = "rules",
    editorial_model: str | None = None,
) -> Phase0Result:
    repo_root = repo_root.resolve()
    adapter_output_dir = adapter_output_dir.resolve()
    market = load_json(adapter_output_dir / "market_pack.json")
    news = load_json(adapter_output_dir / "news_pack.json")
    resolved_run_id = run_id or market.get("run", {}).get("run_id") or news.get("run_id") or adapter_output_dir.parent.name
    if editorial_memo_path:
        editorial = load_json(editorial_memo_path.resolve())
        editorial_generation = {"mode": "provided", "status": "ok"}
    else:
        from .editorial_llm import draft_editorial_memo_auto

        editorial, editorial_generation = draft_editorial_memo_auto(
            resolved_run_id,
            market,
            news,
            mode=editorial_mode,
            model=editorial_model,
        )
    editorial["run_id"] = resolved_run_id

    with TemporaryDirectory() as tmpdir:
        fixture_dir = Path(tmpdir) / "collected_fixture"
        fixture_dir.mkdir()
        _write_json(fixture_dir / "market_pack.json", _with_run_id(market, resolved_run_id))
        _write_json(fixture_dir / "news_pack.json", _with_news_run_id(news, resolved_run_id))
        _write_json(fixture_dir / "editorial_memo.json", editorial)
        result = build_fixture_bundle(
            repo_root=repo_root,
            fixture_dir=fixture_dir,
            run_id=resolved_run_id,
            output_root=output_root,
            render_pdf=render_pdf,
        )

    source_audit = adapter_output_dir / "source_audit.json"
    if source_audit.exists():
        target = result.run_dir / "adapter_outputs" / "source_audit.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        if source_audit.resolve() != target.resolve():
            shutil.copy2(source_audit, target)
    manifest = adapter_output_dir / "manifest.json"
    if manifest.exists():
        target = result.run_dir / "adapter_outputs" / "collector_manifest.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        if manifest.resolve() != target.resolve():
            shutil.copy2(manifest, target)
    generation_path = result.run_dir / "adapter_outputs" / "editorial_generation.json"
    generation_path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(generation_path, editorial_generation)
    return result


def draft_editorial_memo(run_id: str, market: dict[str, Any], news: dict[str, Any]) -> dict[str, Any]:
    indices = market.get("indices", [])
    global_context = market.get("global_context", [])
    events = news.get("events", [])
    evidence_ids = _evidence_ids(market, news)
    story_evidence = evidence_ids[:2] if len(evidence_ids) >= 2 else ["collector-warning-01", "collector-warning-01"]
    title = f"{market.get('run', {}).get('trade_date', run_id)} collected market draft"
    index_summary = _index_summary(indices)
    global_summary = _global_summary(global_context)
    event_summary = _event_summary(events)
    return {
        "schema_version": "editorial_memo.v1",
        "run_id": run_id,
        "title": title,
        "one_liner": "Adapter-collected draft memo for human review before publication.",
        "summary_bullets": [
            index_summary,
            global_summary,
            event_summary,
        ],
        "news_bullets": [
            {
                "event_id": event["event_id"],
                "headline": event.get("title", event["event_id"]),
                "market_connection": "Collected news input; confirm market linkage before publication.",
            }
            for event in events[:6]
        ],
        "stories": [
            {
                "story_id": "story-collected-market-draft",
                "title": "Collected market draft needs editorial review",
                "question": "What does the adapter-collected market snapshot suggest?",
                "observed_facts": [index_summary, event_summary],
                "interpretation": "This is a machine-assembled draft from adapters. Treat it as briefing material, not final editorial judgment.",
                "alternative_hypotheses": ["The collected snapshot may reflect stale or rights-limited prototype inputs."],
                "counterevidence": ["Source audit and human review may change which observations are publishable."],
                "disconfirmation_conditions": ["Refresh adapters, resolve source audit warnings, and approve the editorial memo."],
                "evidence_ids": story_evidence,
                "confidence": "low",
            }
        ],
        "watchpoints": [
            "Refresh adapter data close to publication time.",
            "Resolve source audit warnings before public publication.",
            "Confirm that news events and market moves have an editorially valid relationship.",
        ],
        "host_questions": [
            "Which collected observations are actually publishable?",
            "Which market links need human confirmation before publication?",
        ],
        "chart_requests": ["Adapter index snapshot chart", "Global context tracker chart"],
        "claim_evidence_map": [
            {
                "claim_id": "claim-collected-01",
                "claim": "Adapter output is sufficient for a draft briefing bundle, not public publication.",
                "claim_type": "interpretation",
                "evidence_ids": story_evidence,
            }
        ],
        "approval": {
            "status": "draft",
            "approved_by": None,
            "approved_at": None,
            "notes": "Auto-generated from adapter outputs; requires human editorial approval.",
        },
    }


def _evidence_ids(market: dict[str, Any], news: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    for key in ("indices", "global_context", "observations", "breadth", "flows", "fx", "movers"):
        for item in market.get(key, []):
            value = item.get("evidence_id") or item.get("observation_id")
            if value:
                ids.append(str(value))
    for event in news.get("events", []):
        ids.append(str(event["event_id"]))
        for fact in event.get("facts", []):
            if fact.get("fact_id"):
                ids.append(str(fact["fact_id"]))
    return list(dict.fromkeys(ids))


def _index_summary(indices: list[dict[str, Any]]) -> str:
    if not indices:
        return "No index observations were collected."
    parts = [f"{item.get('symbol', item.get('name', 'index'))} {float(item.get('change_pct', 0)):+.2f}%" for item in indices[:3]]
    return "Collected index snapshot: " + ", ".join(parts) + "."


def _global_summary(items: list[dict[str, Any]]) -> str:
    if not items:
        return "No global context observations were collected."
    parts = [f"{item.get('symbol', 'global')} {float(item.get('value', 0)):,.2f}" for item in items[:3]]
    return "Collected global context: " + ", ".join(parts) + "."


def _event_summary(events: list[dict[str, Any]]) -> str:
    if not events:
        return "No news events were collected."
    return f"Collected {len(events)} news event(s); top event: {events[0].get('title', events[0]['event_id'])}."


def _with_run_id(market: dict[str, Any], run_id: str) -> dict[str, Any]:
    copied = json.loads(json.dumps(market, ensure_ascii=False))
    copied.setdefault("run", {})["run_id"] = run_id
    return copied


def _with_news_run_id(news: dict[str, Any], run_id: str) -> dict[str, Any]:
    copied = json.loads(json.dumps(news, ensure_ascii=False))
    copied["run_id"] = run_id
    return copied


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
