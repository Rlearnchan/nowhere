from __future__ import annotations

import json
from typing import Any
from urllib import request as urlrequest

from .env import DEFAULT_ENV_PATHS, load_env
from .collected import draft_editorial_memo

RESPONSES_URL = "https://api.openai.com/v1/responses"
DEFAULT_MODEL = "gpt-4.1-mini"


class EditorialLlmError(RuntimeError):
    pass


def draft_editorial_memo_with_llm(
    run_id: str,
    market: dict[str, Any],
    news: dict[str, Any],
    model: str | None = None,
    env_paths=DEFAULT_ENV_PATHS,
) -> dict[str, Any]:
    env = load_env(env_paths)
    api_key = env.get("OPENAI_API_KEY")
    if not api_key:
        raise EditorialLlmError("OPENAI_API_KEY is not configured")
    selected_model = model or env.get("NOWHERE_EDITORIAL_MODEL") or DEFAULT_MODEL
    fallback = draft_editorial_memo(run_id, market, news)
    payload = _request_payload(selected_model, run_id, market, news, fallback)
    response = _post_responses(api_key, payload)
    memo = _extract_json_object(response)
    return _repair_memo(memo, fallback, run_id, market, news, selected_model)


def draft_editorial_memo_auto(
    run_id: str,
    market: dict[str, Any],
    news: dict[str, Any],
    mode: str = "auto",
    model: str | None = None,
    env_paths=DEFAULT_ENV_PATHS,
) -> tuple[dict[str, Any], dict[str, Any]]:
    normalized_mode = mode.lower()
    if normalized_mode not in {"auto", "llm", "rules"}:
        raise ValueError("editorial mode must be one of: auto, llm, rules")
    if normalized_mode == "rules":
        return draft_editorial_memo(run_id, market, news), {"mode": "rules", "status": "ok"}
    try:
        memo = draft_editorial_memo_with_llm(run_id, market, news, model=model, env_paths=env_paths)
    except Exception as exc:
        if normalized_mode == "llm":
            raise
        memo = draft_editorial_memo(run_id, market, news)
        memo["approval"]["notes"] = f"Rule-based fallback after LLM draft failed: {exc.__class__.__name__}."
        return memo, {"mode": "auto", "status": "fallback_rules", "reason": str(exc)}
    return memo, {"mode": normalized_mode, "status": "llm", "model": model or load_env(env_paths).get("NOWHERE_EDITORIAL_MODEL") or DEFAULT_MODEL}


def _request_payload(model: str, run_id: str, market: dict[str, Any], news: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    compact_market = {
        "run": market.get("run", {}),
        "indices": market.get("indices", [])[:4],
        "global_context": market.get("global_context", [])[:4],
        "warnings": market.get("run", {}).get("warnings", []),
    }
    compact_news = {
        "news_cutoff": news.get("news_cutoff"),
        "events": news.get("events", [])[:8],
    }
    instructions = (
        "You write a concise Korean market brief editorial_memo JSON. "
        "Return only JSON. Do not invent facts beyond the provided market and news packs. "
        "Use news market_links when present; when absent, say the link needs confirmation. "
        "Keep approval.status as draft. Match the provided editorial_memo.v1 shape exactly."
    )
    user_payload = {
        "run_id": run_id,
        "market_pack": compact_market,
        "news_pack": compact_news,
        "fallback_shape": fallback,
    }
    return {
        "model": model,
        "input": [
            {"role": "system", "content": [{"type": "input_text", "text": instructions}]},
            {"role": "user", "content": [{"type": "input_text", "text": json.dumps(user_payload, ensure_ascii=False)}]},
        ],
        "text": {"format": {"type": "json_object"}},
    }


def _post_responses(api_key: str, payload: dict[str, Any]) -> dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urlrequest.Request(
        RESPONSES_URL,
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "nowhere-editorial-llm/0.1",
        },
    )
    try:
        with urlrequest.urlopen(req, timeout=60) as response:
            return json.loads(response.read().decode("utf-8", errors="replace"))
    except Exception as exc:
        raise EditorialLlmError(f"OpenAI Responses request failed: {exc}") from exc


def _extract_json_object(response: dict[str, Any]) -> dict[str, Any]:
    text = response.get("output_text")
    if not text:
        chunks: list[str] = []
        for item in response.get("output", []) if isinstance(response.get("output"), list) else []:
            for content in item.get("content", []) if isinstance(item, dict) else []:
                if isinstance(content, dict) and content.get("text"):
                    chunks.append(str(content["text"]))
        text = "\n".join(chunks)
    if not text:
        raise EditorialLlmError("OpenAI response did not include output text")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise EditorialLlmError("OpenAI response was not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise EditorialLlmError("OpenAI response JSON was not an object")
    return parsed


def _repair_memo(
    memo: dict[str, Any],
    fallback: dict[str, Any],
    run_id: str,
    market: dict[str, Any],
    news: dict[str, Any],
    model: str,
) -> dict[str, Any]:
    repaired = dict(fallback)
    for key in ("title", "one_liner", "summary_bullets", "news_bullets", "stories", "watchpoints", "host_questions", "chart_requests", "claim_evidence_map"):
        if memo.get(key):
            repaired[key] = memo[key]
    repaired["schema_version"] = "editorial_memo.v1"
    repaired["run_id"] = run_id
    repaired["approval"] = {
        "status": "draft",
        "approved_by": None,
        "approved_at": None,
        "notes": f"Auto-drafted with {model}; requires editorial approval before publication.",
    }
    known_ids = set(_evidence_ids(market, news)) or {"collector-warning-01"}
    repaired["summary_bullets"] = _bounded_strings(repaired.get("summary_bullets"), fallback["summary_bullets"], 3, 6)
    repaired["news_bullets"] = _bounded_news_bullets(repaired.get("news_bullets"), fallback["news_bullets"])
    repaired["stories"] = _bounded_stories(repaired.get("stories"), fallback["stories"], known_ids)
    repaired["watchpoints"] = _bounded_strings(repaired.get("watchpoints"), fallback["watchpoints"], 3, 8)
    repaired["host_questions"] = _bounded_strings(repaired.get("host_questions"), fallback["host_questions"], 2, 6)
    repaired["claim_evidence_map"] = _bounded_claims(repaired.get("claim_evidence_map"), fallback["claim_evidence_map"], known_ids)
    return repaired


def _bounded_strings(value: object, fallback: list[str], min_items: int, max_items: int) -> list[str]:
    items = [str(item) for item in value] if isinstance(value, list) else []
    items = [item for item in items if item.strip()]
    if len(items) < min_items:
        items.extend(fallback)
    return items[:max_items]


def _bounded_news_bullets(value: object, fallback: list[dict[str, Any]]) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return fallback[:8]
    result = []
    for item in value:
        if not isinstance(item, dict):
            continue
        result.append({
            "event_id": str(item.get("event_id") or "event-review"),
            "headline": str(item.get("headline") or item.get("title") or "뉴스 확인 필요"),
            "market_connection": str(item.get("market_connection") or "시장 연결 확인 필요"),
        })
    return (result or fallback)[:8]


def _bounded_stories(value: object, fallback: list[dict[str, Any]], known_ids: set[str]) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return fallback[:2]
    stories = []
    for idx, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            continue
        evidence = [str(ev) for ev in item.get("evidence_ids", []) if str(ev) in known_ids]
        if len(evidence) < 2:
            evidence = list(known_ids)[:2]
        stories.append({
            "story_id": str(item.get("story_id") or f"story-llm-{idx:02d}"),
            "title": str(item.get("title") or "시장 흐름 점검"),
            "question": str(item.get("question") or "오늘 시장에서 확인할 흐름은 무엇인가?"),
            "observed_facts": _bounded_strings(item.get("observed_facts"), fallback[0]["observed_facts"], 2, 6),
            "interpretation": str(item.get("interpretation") or fallback[0]["interpretation"]),
            "alternative_hypotheses": _bounded_strings(item.get("alternative_hypotheses"), fallback[0].get("alternative_hypotheses", []), 0, 4),
            "counterevidence": _bounded_strings(item.get("counterevidence"), fallback[0]["counterevidence"], 1, 4),
            "disconfirmation_conditions": _bounded_strings(item.get("disconfirmation_conditions"), fallback[0]["disconfirmation_conditions"], 1, 4),
            "evidence_ids": evidence[:6],
            "confidence": str(item.get("confidence") if item.get("confidence") in {"low", "medium", "high"} else "low"),
        })
    return (stories or fallback)[:2]


def _bounded_claims(value: object, fallback: list[dict[str, Any]], known_ids: set[str]) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return fallback
    claims = []
    for idx, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            continue
        evidence = [str(ev) for ev in item.get("evidence_ids", []) if str(ev) in known_ids] or list(known_ids)[:1]
        claim_type = item.get("claim_type") if item.get("claim_type") in {"observed_fact", "reported_claim", "interpretation", "hypothesis"} else "interpretation"
        claims.append({
            "claim_id": str(item.get("claim_id") or f"claim-llm-{idx:02d}"),
            "claim": str(item.get("claim") or "시장 흐름 해석은 근거 확인이 필요합니다."),
            "claim_type": claim_type,
            "evidence_ids": evidence,
        })
    return claims or fallback


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
