from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape
import hashlib
import json
import subprocess
import shutil
from pathlib import Path
from typing import Any

from .chart_contracts import validate_chart_payloads
from .contracts import ValidationIssue, load_json, validate_contract


PACK_FILES = {
    "market_pack": "market_pack.json",
    "news_pack": "news_pack.json",
    "editorial_memo": "editorial_memo.json",
}


@dataclass(frozen=True)
class Phase0Result:
    run_id: str
    run_dir: Path
    manifest_path: Path
    validation_report_path: Path
    html_path: Path
    pdf_path: Path | None
    publish_manifest_path: Path


def build_fixture_bundle(
    repo_root: Path,
    fixture_dir: Path,
    run_id: str | None = None,
    output_root: Path | None = None,
    render_pdf: bool = True,
) -> Phase0Result:
    repo_root = repo_root.resolve()
    fixture_dir = fixture_dir.resolve()
    output_root = (output_root or repo_root / "runs").resolve()
    contracts_dir = repo_root / "contracts"

    packs = {name: load_json(fixture_dir / filename) for name, filename in PACK_FILES.items()}
    resolved_run_id = run_id or _infer_run_id(packs)
    run_dir = output_root / resolved_run_id

    _prepare_run_dir(run_dir)
    _copy_inputs(fixture_dir, run_dir)

    contract_issues = _validate_packs(packs, contracts_dir)
    chart_payloads = build_chart_payloads(packs["market_pack"], packs["news_pack"])
    contract_issues.update(validate_chart_payloads(chart_payloads, contracts_dir))
    qa_report = build_qa_report(packs, contract_issues)

    charts_dir = run_dir / "charts"
    render_dir = run_dir / "render"
    qa_dir = run_dir / "qa"
    charts_dir.mkdir(parents=True, exist_ok=True)
    render_dir.mkdir(parents=True, exist_ok=True)
    qa_dir.mkdir(parents=True, exist_ok=True)

    _write_json(charts_dir / "datawrapper_specs.json", chart_payloads["datawrapper"])
    _write_json(charts_dir / "lightweight_series.json", chart_payloads["lightweight"])
    _write_json(qa_dir / "validation_report.json", qa_report)

    html_path = render_dir / "brief.html"
    html_path.write_text(render_html_brief(packs, qa_report), encoding="utf-8")
    pdf_result = render_pdf_from_html(html_path) if render_pdf else {"status": "skipped", "reason": "disabled"}

    publish_manifest_path = build_publish_bundle(
        run_id=resolved_run_id,
        run_dir=run_dir,
        packs=packs,
        qa_report=qa_report,
        pdf_result=pdf_result,
    )

    manifest = build_manifest(resolved_run_id, run_dir, packs, qa_report)
    manifest_path = run_dir / "manifest.json"
    _write_json(manifest_path, manifest)

    return Phase0Result(
        run_id=resolved_run_id,
        run_dir=run_dir,
        manifest_path=manifest_path,
        validation_report_path=qa_dir / "validation_report.json",
        html_path=html_path,
        pdf_path=Path(pdf_result["path"]) if pdf_result.get("path") else None,
        publish_manifest_path=publish_manifest_path,
    )


def build_manifest(run_id: str, run_dir: Path, packs: dict[str, Any], qa_report: dict[str, Any]) -> dict[str, Any]:
    files = [
        "market_pack.json",
        "news_pack.json",
        "editorial_memo.json",
        "charts/datawrapper_specs.json",
        "charts/lightweight_series.json",
        "qa/validation_report.json",
        "render/brief.html",
        "publish/article.json",
        "publish/publish_manifest.json",
    ]
    if (run_dir / "render" / "brief.pdf").exists():
        files.append("render/brief.pdf")
    return {
        "schema_version": "nowhere.phase0_manifest.v1",
        "run_id": run_id,
        "generated_at": _utc_now(),
        "inputs": {name: PACK_FILES[name] for name in PACK_FILES},
        "qa_status": qa_report.get("status"),
        "public_publish_allowed": qa_report.get("public_publish_allowed", False),
        "trade_date": packs.get("market_pack", {}).get("run", {}).get("trade_date"),
        "market_as_of": packs.get("market_pack", {}).get("run", {}).get("market_as_of"),
        "artifacts": [
            {
                "path": file_path,
                "sha256": _sha256(run_dir / file_path),
                "bytes": (run_dir / file_path).stat().st_size,
            }
            for file_path in files
            if (run_dir / file_path).exists()
        ],
    }


def render_pdf_from_html(html_path: Path) -> dict[str, Any]:
    pdf_path = html_path.with_suffix(".pdf")
    weasyprint_result = _render_pdf_with_weasyprint(html_path, pdf_path)
    if weasyprint_result["status"] != "skipped":
        return weasyprint_result
    return _render_pdf_with_libreoffice(html_path, pdf_path)


def _render_pdf_with_weasyprint(html_path: Path, pdf_path: Path) -> dict[str, Any]:
    try:
        from weasyprint import HTML
    except Exception as exc:  # optional dependency
        return {"status": "skipped", "reason": f"weasyprint unavailable: {exc.__class__.__name__}"}

    try:
        HTML(filename=str(html_path)).write_pdf(str(pdf_path))
    except Exception as exc:
        return {"status": "failed", "reason": f"weasyprint conversion failed: {exc}"}
    if not pdf_path.exists():
        return {"status": "failed", "reason": "weasyprint did not create brief.pdf"}
    return {"status": "ok", "path": str(pdf_path), "tool": "weasyprint"}


def _render_pdf_with_libreoffice(html_path: Path, pdf_path: Path) -> dict[str, Any]:
    libreoffice = shutil.which("libreoffice")
    if not libreoffice:
        return {"status": "skipped", "reason": "no PDF renderer found"}

    outdir = html_path.parent
    cmd = [
        libreoffice,
        "--headless",
        "--convert-to",
        "pdf",
        "--outdir",
        str(outdir),
        str(html_path),
    ]
    try:
        completed = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return {"status": "failed", "reason": "libreoffice timed out"}

    if completed.returncode != 0:
        return {
            "status": "failed",
            "reason": "libreoffice conversion failed",
            "stderr": completed.stderr.strip(),
        }
    if not pdf_path.exists():
        return {
            "status": "failed",
            "reason": "libreoffice did not create brief.pdf",
            "stdout": completed.stdout.strip(),
            "stderr": completed.stderr.strip(),
        }
    return {"status": "ok", "path": str(pdf_path), "tool": "libreoffice"}


def build_publish_bundle(
    run_id: str,
    run_dir: Path,
    packs: dict[str, Any],
    qa_report: dict[str, Any],
    pdf_result: dict[str, Any],
) -> Path:
    market = packs["market_pack"]
    editorial = packs["editorial_memo"]
    publish_dir = run_dir / "publish"
    site_dir = publish_dir / "site"
    data_dir = publish_dir / "data"
    publish_dir.mkdir(parents=True, exist_ok=True)
    site_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)

    slug = run_id.replace("_", "-").replace("/", "-")
    shutil.copy2(run_dir / "render" / "brief.html", site_dir / "index.html")
    if pdf_result.get("status") == "ok":
        shutil.copy2(run_dir / "render" / "brief.pdf", site_dir / "brief.pdf")
    for source, target in (
        (run_dir / "charts" / "datawrapper_specs.json", data_dir / "datawrapper_specs.json"),
        (run_dir / "charts" / "lightweight_series.json", data_dir / "lightweight_series.json"),
        (run_dir / "qa" / "validation_report.json", data_dir / "validation_report.json"),
    ):
        shutil.copy2(source, target)
    (site_dir / "chart_bootstrap.js").write_text(render_lightweight_bootstrap_js(), encoding="utf-8")

    article = {
        "schema_version": "nowhere.article.v1",
        "run_id": run_id,
        "slug": slug,
        "title": editorial["title"],
        "one_liner": editorial["one_liner"],
        "trade_date": market["run"]["trade_date"],
        "market_as_of": market["run"]["market_as_of"],
        "qa_status": qa_report["status"],
        "public_publish_allowed": qa_report["public_publish_allowed"],
        "summary_bullets": editorial.get("summary_bullets", []),
        "watchpoints": editorial.get("watchpoints", []),
        "host_questions": editorial.get("host_questions", []),
        "artifacts": {
            "html": "site/index.html",
            "pdf": "site/brief.pdf" if pdf_result.get("status") == "ok" else None,
            "datawrapper_specs": "data/datawrapper_specs.json",
            "lightweight_series": "data/lightweight_series.json",
            "lightweight_bootstrap": "site/chart_bootstrap.js",
            "qa_report": "data/validation_report.json",
        },
    }
    _write_json(publish_dir / "article.json", article)

    manifest = {
        "schema_version": "nowhere.publish_manifest.v1",
        "run_id": run_id,
        "slug": slug,
        "target": "buykings.kr",
        "mode": "dry-run",
        "generated_at": _utc_now(),
        "public_publish_allowed": qa_report["public_publish_allowed"],
        "pdf": pdf_result,
        "files": _publish_files_with_integrity(
            run_dir,
            [
                {"local_path": "publish/site/index.html", "remote_role": "article_html"},
                {"local_path": "publish/site/chart_bootstrap.js", "remote_role": "article_asset"},
                {"local_path": "publish/site/brief.pdf", "remote_role": "article_pdf", "optional": True},
                {"local_path": "publish/article.json", "remote_role": "article_data"},
                {"local_path": "publish/data/datawrapper_specs.json", "remote_role": "chart_specs"},
                {"local_path": "publish/data/lightweight_series.json", "remote_role": "chart_series"},
                {"local_path": "publish/data/validation_report.json", "remote_role": "qa"},
            ],
        ),
    }
    manifest_path = publish_dir / "publish_manifest.json"
    _write_json(manifest_path, manifest)
    return manifest_path


def build_chart_payloads(market: dict[str, Any], news: dict[str, Any]) -> dict[str, Any]:
    source_rights = {src["source_id"]: src.get("rights_class", "unknown") for src in market.get("sources", []) + news.get("sources", [])}

    def metadata(source_ids: list[str], evidence_ids: list[str]) -> dict[str, Any]:
        return {
            "source_ids": sorted(set(source_ids)),
            "evidence_ids": sorted(set(evidence_ids)),
            "rights_classes": sorted({source_rights.get(source_id, "unknown") for source_id in source_ids}),
        }

    range_rows = [
        {
            "market": item["symbol"],
            "low": item["low"],
            "open": item["open"],
            "prev_close": item["prev_close"],
            "last": item["last"],
            "high": item["high"],
            "change_pct": item["change_pct"],
            "as_of": item["as_of"],
            "source_id": item["source_id"],
            "evidence_id": item["evidence_id"],
            "rights_class": item.get("rights_class"),
            "prototype_only": item.get("prototype_only", False),
            "redistribution_allowed": item.get("redistribution_allowed", True),
            "quality_flags": item.get("quality_flags", []),
        }
        for item in market.get("indices", [])
    ]
    breadth_rows = [
        {
            "market": item["market"],
            "advancers": item["advancers"],
            "unchanged": item["unchanged"],
            "decliners": item["decliners"],
            "advancer_ratio_ex_flat_pct": item["advancer_ratio_ex_flat_pct"],
            "as_of": item["as_of"],
            "source_id": item["source_id"],
            "evidence_id": item["evidence_id"],
        }
        for item in market.get("breadth", [])
    ]
    flow_rows = [
        {
            "market": item["market"],
            "participant": item["participant"],
            "net_value_krw_100m": item["net_value_krw_100m"],
            "as_of": item["as_of"],
            "source_id": item["source_id"],
            "evidence_id": item["evidence_id"],
        }
        for item in market.get("flows", [])
    ]
    catalyst_rows = [
        {
            "event_id": event["event_id"],
            "time": event["first_seen_at"],
            "title": event["title"],
            "category": event["category"],
            "significance_hint": event.get("significance_hint"),
            "sources": ",".join(event["sources"]),
        }
        for event in news.get("events", [])
    ]
    sector_rows = [
        {
            "rank_group": group,
            "market": item["market"],
            "sector": item["sector"],
            "change_pct": item["change_pct"],
            "last": item["last"],
            "as_of": item["as_of"],
            "source_id": item["source_id"],
            "evidence_id": item["evidence_id"],
        }
        for group, rows in market.get("sector_rankings", {}).items()
        for item in rows
    ]
    featured_rows = [
        {
            "ticker": item["ticker"],
            "name": item["name"],
            "market": item["market"],
            "last": item["last"],
            "change_pct": item["change_pct"],
            "trading_value_krw": item.get("trading_value_krw"),
            "as_of": item["as_of"],
            "source_id": item["source_id"],
            "evidence_id": item["evidence_id"],
        }
        for item in market.get("featured_stocks", [])
    ]

    datawrapper = {
        "schema_version": "nowhere.datawrapper_specs.v1",
        "generated_at": _utc_now(),
        "charts": [
            {
                "chart_id": "market-day-range",
                "tool": "datawrapper",
                "chart_type": "d3-bars",
                "title": "KOSPI/KOSDAQ day range",
                "table": {"columns": ["market", "low", "open", "prev_close", "last", "high", "change_pct", "as_of", "source_id", "evidence_id", "rights_class", "prototype_only", "redistribution_allowed", "quality_flags"], "rows": range_rows},
                "visualize": {"baseline_column": "prev_close", "value_column": "last", "range_columns": ["low", "high"]},
                "metadata": metadata([row["source_id"] for row in range_rows], [row["evidence_id"] for row in range_rows]),
            },
            {
                "chart_id": "market-breadth",
                "tool": "datawrapper",
                "chart_type": "stacked-bars",
                "title": "Market breadth comparison",
                "table": {"columns": ["market", "advancers", "unchanged", "decliners", "advancer_ratio_ex_flat_pct", "as_of", "source_id", "evidence_id"], "rows": breadth_rows},
                "visualize": {"stack_columns": ["advancers", "unchanged", "decliners"], "label_column": "market"},
                "metadata": metadata([row["source_id"] for row in breadth_rows], [row["evidence_id"] for row in breadth_rows]),
            },
            {
                "chart_id": "investor-flows",
                "tool": "datawrapper",
                "chart_type": "d3-bars",
                "title": "Investor and program flows",
                "table": {"columns": ["market", "participant", "net_value_krw_100m", "as_of", "source_id", "evidence_id"], "rows": flow_rows},
                "visualize": {"label_column": "participant", "value_column": "net_value_krw_100m", "split_column": "market"},
                "metadata": metadata([row["source_id"] for row in flow_rows], [row["evidence_id"] for row in flow_rows]),
            },
            {
                "chart_id": "sector-temperature",
                "tool": "datawrapper",
                "chart_type": "d3-bars",
                "title": "Sector temperature top/bottom",
                "table": {"columns": ["rank_group", "market", "sector", "change_pct", "last", "as_of", "source_id", "evidence_id"], "rows": sector_rows},
                "visualize": {"label_column": "sector", "value_column": "change_pct", "split_column": "rank_group"},
                "metadata": metadata([row["source_id"] for row in sector_rows], [row["evidence_id"] for row in sector_rows]),
            },
            {
                "chart_id": "featured-stocks",
                "tool": "datawrapper",
                "chart_type": "tables",
                "title": "News-linked featured stocks",
                "table": {"columns": ["ticker", "name", "market", "last", "change_pct", "trading_value_krw", "as_of", "source_id", "evidence_id"], "rows": featured_rows},
                "visualize": {"sort_column": "change_pct"},
                "metadata": metadata([row["source_id"] for row in featured_rows], [row["evidence_id"] for row in featured_rows]),
            },
            {
                "chart_id": "afternoon-catalysts",
                "tool": "datawrapper",
                "chart_type": "tables",
                "title": "Afternoon catalysts",
                "table": {"columns": ["event_id", "time", "title", "category", "significance_hint", "sources"], "rows": catalyst_rows},
                "visualize": {"sort_column": "time"},
                "metadata": metadata([source_id for event in news.get("events", []) for source_id in event["sources"]], [event["event_id"] for event in news.get("events", [])]),
            },
        ],
    }

    datawrapper["charts"] = [
        chart
        for chart in datawrapper["charts"]
        if chart.get("table", {}).get("rows")
    ]

    lightweight = {
        "schema_version": "nowhere.lightweight_series.v1",
        "generated_at": _utc_now(),
        "charts": [
            {
                "chart_id": "index-range-series",
                "tool": "lightweight-charts",
                "container_hint": "tracker",
                "options": {
                    "layout": {"background": {"color": "#f4f6f8"}, "textColor": "#17212b"},
                    "rightPriceScale": {"borderVisible": False},
                    "timeScale": {"borderVisible": False},
                },
                "series": [
                    {
                        "series_id": item["symbol"],
                        "type": "Candlestick",
                        "data": [
                            {
                                "time": item["as_of"][:10],
                                "open": item["open"],
                                "high": item["high"],
                                "low": item["low"],
                                "close": item["last"],
                            }
                        ],
                        "markers": [
                            {"time": item["as_of"][:10], "position": "aboveBar", "shape": "circle", "text": f"{item['change_pct']:+.2f}%"}
                        ],
                        "metadata": {
                            "as_of": item["as_of"],
                            "source_id": item["source_id"],
                            "evidence_id": item["evidence_id"],
                            "rights_class": item.get("rights_class"),
                            "prototype_only": item.get("prototype_only", False),
                            "redistribution_allowed": item.get("redistribution_allowed", True),
                            "quality_flags": item.get("quality_flags", []),
                        },
                    }
                    for item in market.get("indices", [])
                ],
                "metadata": metadata([item["source_id"] for item in market.get("indices", [])], [item["evidence_id"] for item in market.get("indices", [])]),
            }
        ],
    }

    return {"datawrapper": datawrapper, "lightweight": lightweight}


def build_qa_report(
    packs: dict[str, Any],
    contract_issues: dict[str, list[ValidationIssue]],
) -> dict[str, Any]:
    market = packs["market_pack"]
    news = packs["news_pack"]
    editorial = packs["editorial_memo"]

    known_evidence = _known_evidence_ids(market, news)
    missing_evidence = _missing_editorial_evidence(editorial, known_evidence)
    rights = _rights_summary(market, news)
    approval = editorial.get("approval", {})
    warnings: list[str] = []

    if approval.get("status") != "approved":
        warnings.append("editorial memo is not approved; public publication is blocked")
    if rights["restricted_or_prototype_sources"]:
        warnings.append("restricted/prototype source rights are present")
    if missing_evidence:
        warnings.append("one or more editorial evidence IDs could not be resolved")

    flat_contract_issues = {
        name: [issue.__dict__ for issue in issues]
        for name, issues in contract_issues.items()
    }

    status = "ok"
    if any(contract_issues.values()) or missing_evidence:
        status = "blocked"
    elif warnings:
        status = "review_needed"

    return {
        "generated_at": _utc_now(),
        "status": status,
        "public_publish_allowed": status == "ok" and approval.get("status") == "approved",
        "contract_validation": flat_contract_issues,
        "evidence_validation": {
            "known_evidence_count": len(known_evidence),
            "missing_evidence_ids": missing_evidence,
        },
        "approval": approval,
        "rights": rights,
        "warnings": warnings,
    }


def build_reader_status_cards(packs: dict[str, Any], qa_report: dict[str, Any]) -> list[dict[str, str]]:
    market = packs["market_pack"]
    news = packs["news_pack"]
    indices = market.get("indices", [])
    global_context = market.get("global_context", [])
    events = news.get("events", [])

    if not indices:
        korea_tone = "blocked"
        korea_status = "시장 지수 없음"
        korea_detail = "한국 시장 기준 데이터가 아직 연결되지 않았습니다."
    elif any(str(item.get("source_id", "")).startswith("src-krx") for item in indices):
        korea_tone = "ok"
        korea_status = "KRX 기준"
        korea_detail = "한국 지수는 KRX 공식 API 스냅샷을 기준으로 표시합니다."
    elif any(item.get("redistribution_allowed") is False for item in indices):
        korea_tone = "review"
        korea_status = "대체 데이터"
        korea_detail = "프로토타입 스냅샷이 포함되어 공개 재배포 기준 확인이 필요합니다."
    else:
        korea_tone = "ok"
        korea_status = "수집 완료"
        korea_detail = "한국 시장 지수 스냅샷이 수집되었습니다."

    global_flags = {flag for item in global_context for flag in item.get("quality_flags", [])}
    if not global_context:
        global_tone = "review"
        global_status = "보조지표 없음"
        global_detail = "해외 ETF 등 글로벌 비교 지표가 아직 비어 있습니다."
    elif "market_data_stale" in global_flags:
        global_tone = "review"
        global_status = "최신성 확인"
        global_detail = "글로벌 보조지표의 마지막 가격 시점이 수집 시점보다 오래되었습니다."
    else:
        global_tone = "review" if global_flags else "ok"
        global_status = "보조 맥락"
        global_detail = "Yahoo Finance 기반 글로벌 가격은 방향성 참고용으로 함께 표시합니다."

    news_flags = {flag for event in events for flag in event.get("quality_flags", [])}
    if not events:
        news_tone = "blocked"
        news_status = "뉴스 없음"
        news_detail = "뉴스 근거가 아직 연결되지 않았습니다."
    elif news_flags.intersection({"missing_market_links", "missing_reported_claims", "unverified_news_event"}):
        news_tone = "review"
        news_status = "연결 확인"
        news_detail = "뉴스 원문은 수집됐고, 시장 연결과 요약 근거는 보강 대상입니다."
    else:
        news_tone = "ok"
        news_status = "근거 연결"
        news_detail = "뉴스 이벤트와 시장 연결 근거가 함께 정리되어 있습니다."

    approval = packs["editorial_memo"].get("approval", {})
    if approval.get("status") == "approved" and qa_report.get("status") == "ok":
        editorial_tone = "ok"
        editorial_status = "게시 가능"
        editorial_detail = "편집 승인과 데이터 검사가 모두 통과했습니다."
    elif qa_report.get("status") == "blocked":
        editorial_tone = "blocked"
        editorial_status = "보완 필요"
        editorial_detail = "필수 근거 또는 계약 검증에 막힌 항목이 있습니다."
    else:
        editorial_tone = "review"
        editorial_status = "초안"
        editorial_detail = "자동 생성 초안입니다. 핵심 흐름과 근거를 확인하며 읽어주세요."

    return [
        {"label": "한국 시장", "status": korea_status, "detail": korea_detail, "tone": korea_tone},
        {"label": "글로벌 맥락", "status": global_status, "detail": global_detail, "tone": global_tone},
        {"label": "뉴스 근거", "status": news_status, "detail": news_detail, "tone": news_tone},
        {"label": "브리프 상태", "status": editorial_status, "detail": editorial_detail, "tone": editorial_tone},
    ]


def reader_status_label(qa_status: str) -> str:
    if qa_status == "ok":
        return "읽기 준비"
    if qa_status == "blocked":
        return "보완 필요"
    return "초안"


def render_html_brief(packs: dict[str, Any], qa_report: dict[str, Any]) -> str:
    market = packs["market_pack"]
    news = packs["news_pack"]
    editorial = packs["editorial_memo"]
    indices = market.get("indices", [])
    breadth = {item["market"]: item for item in market.get("breadth", [])}

    index_cards = "\n".join(
        f"""
        <section class="metric">
          <h3>{escape(item['name'])}</h3>
          <p class="value">{item['last']:,.2f}</p>
          <p class="change {'up' if item['change_pct'] >= 0 else 'down'}">{item['change_pct']:+.2f}%</p>
          <p>Range {item['low']:,.2f} - {item['high']:,.2f} · As of {escape(item['as_of'])}</p>
        </section>
        """
        for item in indices
    )
    breadth_rows = "\n".join(
        f"<tr><td>{escape(item['market'])}</td><td>{item['advancers']}</td><td>{item['unchanged']}</td><td>{item['decliners']}</td><td>{item['advancer_ratio_ex_flat_pct']:.1f}%</td></tr>"
        for item in market.get("breadth", [])
    )
    flow_rows = "\n".join(
        f"<tr><td>{escape(item['market'])}</td><td>{escape(item['participant'])}</td><td>{item['net_value_krw_100m']:+,.0f}</td><td>{escape(item['source_id'])}</td></tr>"
        for item in market.get("flows", [])
    )
    global_rows = "\n".join(
        f"<tr><td>{escape(item['symbol'])}</td><td>{item['value']:,.2f}</td><td>{item.get('change_pct', 0):+.2f}%</td><td>{escape(item.get('window_start', ''))}</td><td>{escape(item.get('window_end', item['as_of']))}</td></tr>"
        for item in market.get("global_context", [])
    )
    featured_rows_html = "\n".join(
        f"<tr><td>{escape(item['name'])}</td><td>{escape(item['ticker'])}</td><td>{item['last']:,.0f}</td><td class='{'up' if item['change_pct'] >= 0 else 'down'}'>{item['change_pct']:+.2f}%</td><td>{_format_optional_krw(item.get('trading_value_krw'))}</td><td>{escape(item['as_of'])}</td></tr>"
        for item in market.get("featured_stocks", [])
    )
    sector_rows_html = "\n".join(
        f"<tr><td>{'상위' if group == 'top' else '하위'}</td><td>{escape(item['market'])}</td><td>{escape(item['sector'])}</td><td class='{'up' if item['change_pct'] >= 0 else 'down'}'>{item['change_pct']:+.2f}%</td><td>{escape(item['as_of'])}</td></tr>"
        for group, rows in market.get("sector_rankings", {}).items()
        for item in rows
    )
    summary = "\n".join(f"<li>{escape(item)}</li>" for item in editorial.get("summary_bullets", []))
    news_items = "\n".join(
        f"<li><strong>{escape(item['headline'])}</strong><br>{escape(item['market_connection'])}</li>"
        for item in editorial.get("news_bullets", [])
    )
    stories = "\n".join(_render_story(story) for story in editorial.get("stories", []))
    watchpoints = "\n".join(f"<li>{escape(item)}</li>" for item in editorial.get("watchpoints", []))
    source_items = market.get("sources", []) + news.get("sources", [])
    sources = "\n".join(
        f"<li><span>{escape(src['source_id'])}</span><strong>{escape(src['name'])}</strong><em>{escape(src.get('rights_class', ''))}</em></li>"
        for src in source_items
    )
    source_chips = "\n".join(
        f'<span class="source-chip">{escape(src.get("rights_class", "unknown"))}</span>'
        for src in source_items
    )
    status_cards = "\n".join(
        f"""
        <section class="status-card {escape(card['tone'])}">
          <p class="status-label">{escape(card['label'])}</p>
          <strong>{escape(card['status'])}</strong>
          <p>{escape(card['detail'])}</p>
        </section>
        """
        for card in build_reader_status_cards(packs, qa_report)
    )
    qa_warnings = "\n".join(f"<li>{escape(item)}</li>" for item in qa_report.get("warnings", []))
    qa_badge_class = "ok" if qa_report["status"] == "ok" else "review" if qa_report["status"] == "review_needed" else "blocked"
    kospi_breadth = breadth.get("KOSPI", {}).get("advancer_ratio_ex_flat_pct", 0)
    kosdaq_breadth = breadth.get("KOSDAQ", {}).get("advancer_ratio_ex_flat_pct", 0)

    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <title>{escape(editorial['title'])}</title>
  <style>
    :root {{ color-scheme: light; --ink: #18222d; --muted: #5f6f7d; --line: #d9e0e7; --panel: #ffffff; --wash: #f3f6f8; --accent: #185b73; --up: #c8463a; --down: #2f6fb0; --warn: #9a6a12; }}
    body {{ margin: 0; background: var(--wash); color: var(--ink); font-family: "Noto Sans CJK KR", "Apple SD Gothic Neo", Arial, sans-serif; }}
    main {{ max-width: 1040px; margin: 0 auto; padding: 28px 24px 56px; }}
    header {{ border-top: 6px solid #102332; padding-top: 22px; }}
    h1 {{ margin: 8px 0 0; color: #102332; font-size: 34px; line-height: 1.18; letter-spacing: 0; }}
    h2 {{ margin: 32px 0 12px; color: #102332; font-size: 20px; }}
    h3 {{ margin: 0 0 8px; color: #263a4d; font-size: 14px; }}
    p, li, td, th {{ font-size: 14px; line-height: 1.55; }}
    .topline, .source-strip {{ display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }}
    .meta {{ color: var(--muted); font-size: 12px; }}
    .one-liner {{ max-width: 820px; font-size: 18px; color: #2d4050; }}
    .badge, .source-chip {{ display: inline-flex; align-items: center; border: 1px solid var(--line); background: #fff; border-radius: 999px; padding: 4px 8px; font-size: 12px; color: #435363; }}
    .badge.ok {{ border-color: #8ab69b; color: #245b3b; }}
    .badge.review {{ border-color: #d8a63c; color: var(--warn); }}
    .badge.blocked {{ border-color: #c8463a; color: #9d2f26; }}
    .source-chip {{ background: #eef3f6; }}
    .grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }}
    .status-grid {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin-top: 18px; }}
    .status-card, .metric, .panel {{ background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 16px; }}
    .status-card {{ min-height: 116px; }}
    .status-card strong {{ display: block; margin: 4px 0 6px; font-size: 17px; color: #102332; }}
    .status-card p {{ margin: 0; color: #4e6070; }}
    .status-label {{ color: var(--muted) !important; font-size: 12px; }}
    .status-card.ok {{ border-top: 4px solid #4b9b68; }}
    .status-card.review {{ border-top: 4px solid #d8a63c; }}
    .status-card.blocked {{ border-top: 4px solid #c8463a; }}
    .metric {{ display: grid; gap: 4px; }}
    .value {{ margin: 0; font-size: 30px; font-weight: 700; color: #102332; }}
    .change {{ margin: 0; font-weight: 700; }}
    .up {{ color: var(--up); }}
    .down {{ color: var(--down); }}
    .brief-grid {{ display: grid; grid-template-columns: minmax(0, 1.2fr) minmax(280px, .8fr); gap: 12px; align-items: start; }}
    .summary-list {{ margin: 0; padding-left: 18px; }}
    table {{ width: 100%; border-collapse: collapse; background: white; margin-bottom: 10px; }}
    th, td {{ border-bottom: 1px solid var(--line); padding: 8px; text-align: left; vertical-align: top; }}
    th {{ color: #263a4d; background: #f8fafb; }}
    .qa {{ border-left: 4px solid #d8a63c; padding-left: 12px; color: #465866; }}
    .qa-list {{ margin: 8px 0 0; padding-left: 18px; color: #5b4a22; }}
    .chart-shell {{ min-height: 280px; background: white; border: 1px solid var(--line); border-radius: 8px; padding: 12px; }}
    .chart-fallback {{ margin: 0; color: var(--muted); }}
    .chart-legend {{ display: flex; flex-wrap: wrap; gap: 8px; margin: 10px 0 0; padding: 0; list-style: none; }}
    .chart-legend li {{ display: inline-flex; border: 1px solid var(--line); border-radius: 999px; padding: 4px 8px; font-size: 12px; color: #465866; }}
    .embed-list {{ display: grid; gap: 10px; margin-top: 10px; }}
    .embed-list a {{ color: #0f5f8f; font-weight: 700; text-decoration: none; }}
    .source-list {{ display: grid; gap: 8px; margin: 0; padding: 0; list-style: none; }}
    .source-list li {{ display: grid; grid-template-columns: 150px 1fr auto; gap: 10px; border-bottom: 1px solid var(--line); padding: 7px 0; }}
    .source-list span, .source-list em {{ color: var(--muted); font-size: 12px; font-style: normal; }}
    @media (max-width: 900px) {{ .status-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }} }}
    @media (max-width: 760px) {{ main {{ padding: 22px 14px 44px; }} .grid, .brief-grid, .status-grid {{ grid-template-columns: 1fr; }} h1 {{ font-size: 28px; }} .source-list li {{ grid-template-columns: 1fr; gap: 2px; }} }}
    @media print {{ body {{ background: white; }} main {{ max-width: none; padding: 18mm; }} .panel, .metric, table {{ break-inside: avoid; }} }}
  </style>
</head>
<body>
<main>
  <header>
    <div class="topline">
      <span class="badge {qa_badge_class}">데이터 상태 {escape(reader_status_label(qa_report['status']))}</span>
      <span class="meta">NOWHERE NOON BRIEF</span>
      <span class="meta">{escape(market['run']['market_as_of'])}</span>
    </div>
    <h1>{escape(editorial['title'])}</h1>
    <p class="one-liner">{escape(editorial['one_liner'])}</p>
    <div class="source-strip">{source_chips}</div>
    <div class="status-grid">{status_cards}</div>
  </header>

  <h2>Market Snapshot</h2>
  <div class="brief-grid">
    <div class="grid">{index_cards}</div>
    <section class="panel">
      <h3>Briefing pulse</h3>
      <p>KOSPI breadth {kospi_breadth:.1f}% · KOSDAQ breadth {kosdaq_breadth:.1f}%</p>
      <ul class="summary-list">{summary}</ul>
    </section>
  </div>

  <h2>Tracker Chart Preview</h2>
  <section class="chart-shell" id="nowhere-lightweight-chart" data-chart-src="data/lightweight_series.json">
    <p class="chart-fallback">Loading tracker chart payload...</p>
  </section>
  <section class="panel" id="nowhere-datawrapper-embeds" data-result-src="data/datawrapper_result.json">
    <span class="badge review">Datawrapper publish pending</span>
  </section>

  <h2>Market Structure</h2>
  <table><thead><tr><th>Market</th><th>Up</th><th>Flat</th><th>Down</th><th>Up ratio</th></tr></thead><tbody>{breadth_rows}</tbody></table>
  <table><thead><tr><th>Market</th><th>Participant</th><th>Net KRW 100m</th><th>Source</th></tr></thead><tbody>{flow_rows}</tbody></table>
  <table><thead><tr><th>Global</th><th>Latest</th><th>Window change</th><th>Start</th><th>End</th></tr></thead><tbody>{global_rows}</tbody></table>

  <h2>특징주</h2>
  <table><thead><tr><th>종목</th><th>코드</th><th>현재가</th><th>등락률</th><th>거래대금</th><th>기준시각</th></tr></thead><tbody>{featured_rows_html}</tbody></table>

  <h2>업종 온도계</h2>
  <table><thead><tr><th>구분</th><th>시장</th><th>업종/지수</th><th>등락률</th><th>기준시각</th></tr></thead><tbody>{sector_rows_html}</tbody></table>

  <h2>News And Catalysts</h2>
  <ul>{news_items}</ul>

  <h2>Stories</h2>
  {stories}

  <h2>Watchpoints</h2>
  <ul>{watchpoints}</ul>

  <h2>데이터 기준</h2>
  <section class="panel">
    <p class="qa">브리프 상태: {escape(reader_status_label(qa_report['status']))} · 편집 상태: {escape(editorial['approval']['status'])}</p>
    <ul class="qa-list">{qa_warnings}</ul>
  </section>
  <ul class="source-list">{sources}</ul>
</main>
<script src="chart_bootstrap.js" defer></script>
</body>
</html>
"""


def render_lightweight_bootstrap_js() -> str:
    return """
(function () {
  const container = document.getElementById('nowhere-lightweight-chart');
  const datawrapperContainer = document.getElementById('nowhere-datawrapper-embeds');

  function showFallback(message, chart) {
    if (!container) return;
    const parts = chart && chart.series ? chart.series.map((series) => {
      const point = series.data && series.data[0] ? series.data[0] : {};
      return `<li>${series.series_id}: ${point.close ?? 'n/a'}</li>`;
    }).join('') : '';
    container.innerHTML = `<p class="chart-fallback">${message}</p>${parts ? `<ul>${parts}</ul>` : ''}`;
  }

  function renderDatawrapperResult(payload) {
    if (!datawrapperContainer) return;
    const charts = payload && Array.isArray(payload.charts) ? payload.charts.filter((chart) => chart.public_url) : [];
    if (!charts.length) {
      datawrapperContainer.innerHTML = '<span class="badge review">Datawrapper publish pending</span>';
      return;
    }
    const links = charts.map((chart) => (
      `<p><a href="${chart.public_url}" target="_blank" rel="noopener">${chart.chart_id}</a><br><span class="meta">${chart.datawrapper_id || ''}</span></p>`
    )).join('');
    datawrapperContainer.innerHTML = `<span class="badge">Datawrapper published</span><div class="embed-list">${links}</div>`;
  }

  function loadDatawrapperResult() {
    if (!datawrapperContainer) return;
    const src = datawrapperContainer.getAttribute('data-result-src') || 'data/datawrapper_result.json';
    fetch(src)
      .then((response) => response.ok ? response.json() : Promise.reject(new Error('missing datawrapper result')))
      .then(renderDatawrapperResult)
      .catch(() => renderDatawrapperResult({ charts: [] }));
  }

  function loadLibrary() {
    if (window.LightweightCharts) return Promise.resolve();
    return new Promise((resolve, reject) => {
      const script = document.createElement('script');
      script.src = 'https://unpkg.com/lightweight-charts@4.2.3/dist/lightweight-charts.standalone.production.js';
      script.async = true;
      script.onload = resolve;
      script.onerror = reject;
      document.head.appendChild(script);
    });
  }

  function render(payload) {
    const chartSpec = payload.charts && payload.charts[0];
    if (!chartSpec) {
      showFallback('No tracker chart payload found.');
      return;
    }
    if (!window.LightweightCharts) {
      showFallback('Tracker chart library unavailable; showing latest values.', chartSpec);
      return;
    }
    container.innerHTML = '';
    const chart = window.LightweightCharts.createChart(container, {
      width: container.clientWidth || 760,
      height: 260,
      ...chartSpec.options,
    });
    chartSpec.series.forEach((seriesSpec) => {
      const series = chart.addCandlestickSeries({ title: seriesSpec.series_id });
      series.setData(seriesSpec.data || []);
      if (seriesSpec.markers) series.setMarkers(seriesSpec.markers);
    });
    const legend = document.createElement('ul');
    legend.className = 'chart-legend';
    legend.innerHTML = chartSpec.series.map((seriesSpec) => {
      const point = seriesSpec.data && seriesSpec.data[0] ? seriesSpec.data[0] : {};
      const meta = seriesSpec.metadata || {};
      const review = meta.redistribution_allowed === false ? ' · review only' : '';
      return `<li>${seriesSpec.series_id}: ${point.close ?? 'n/a'}${review}</li>`;
    }).join('');
    container.appendChild(legend);
    chart.timeScale().fitContent();
    const resize = () => {
      chart.applyOptions({ width: container.clientWidth || 760 });
    };
    if (window.ResizeObserver) {
      new ResizeObserver(resize).observe(container);
    } else {
      window.addEventListener('resize', resize);
    }
  }

  if (container) {
    const src = container.getAttribute('data-chart-src') || 'data/lightweight_series.json';
    fetch(src)
      .then((response) => response.json())
      .then((payload) => loadLibrary().then(() => render(payload)).catch(() => render(payload)))
      .catch(() => showFallback('Unable to load tracker chart payload.'));
  }
  loadDatawrapperResult();
})();
"""


def _format_optional_krw(value: Any) -> str:
    if value is None:
        return ""
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return str(value)


def _render_story(story: dict[str, Any]) -> str:
    facts = "\n".join(f"<li>{escape(item)}</li>" for item in story.get("observed_facts", []))
    counters = "\n".join(f"<li>{escape(item)}</li>" for item in story.get("counterevidence", []))
    conditions = "\n".join(f"<li>{escape(item)}</li>" for item in story.get("disconfirmation_conditions", []))
    evidence = ", ".join(story.get("evidence_ids", []))
    return f"""
    <section class="panel">
      <h3>{escape(story['title'])}</h3>
      <p><strong>Question:</strong> {escape(story['question'])}</p>
      <p>{escape(story['interpretation'])}</p>
      <p><strong>Observed facts</strong></p>
      <ul>{facts}</ul>
      <p><strong>Counterevidence</strong></p>
      <ul>{counters}</ul>
      <p><strong>Disconfirmation conditions</strong></p>
      <ul>{conditions}</ul>
      <p class="meta">Evidence: {escape(evidence)} · Confidence: {escape(story['confidence'])}</p>
    </section>
    """


def _validate_packs(
    packs: dict[str, Any],
    contracts_dir: Path,
) -> dict[str, list[ValidationIssue]]:
    return {
        name: validate_contract(packs[name], load_json(contracts_dir / filename))
        for name, filename in {
            "market_pack": "market_pack.schema.json",
            "news_pack": "news_pack.schema.json",
            "editorial_memo": "editorial_memo.schema.json",
        }.items()
    }


def _known_evidence_ids(market: dict[str, Any], news: dict[str, Any]) -> set[str]:
    known: set[str] = set()
    for key in ("indices", "breadth", "flows", "fx", "global_context", "movers"):
        for item in market.get(key, []):
            if "evidence_id" in item:
                known.add(item["evidence_id"])
    for item in market.get("observations", []):
        known.add(item["observation_id"])
    for event in news.get("events", []):
        known.add(event["event_id"])
        for fact in event.get("facts", []):
            known.add(fact["fact_id"])
    return known


def _missing_editorial_evidence(editorial: dict[str, Any], known: set[str]) -> list[str]:
    referenced: set[str] = set()
    for story in editorial.get("stories", []):
        referenced.update(story.get("evidence_ids", []))
    for claim in editorial.get("claim_evidence_map", []):
        referenced.update(claim.get("evidence_ids", []))
    return sorted(item for item in referenced if item not in known)


def _rights_summary(market: dict[str, Any], news: dict[str, Any]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    restricted: list[str] = []
    for source in market.get("sources", []) + news.get("sources", []):
        rights_class = source.get("rights_class", "unknown")
        counts[rights_class] = counts.get(rights_class, 0) + 1
        note = source.get("note", "")
        if rights_class == "public_web_restricted" or "prototype" in note.lower():
            restricted.append(source["source_id"])
    return {
        "counts_by_rights_class": counts,
        "restricted_or_prototype_sources": sorted(restricted),
    }


def _infer_run_id(packs: dict[str, Any]) -> str:
    return (
        packs.get("market_pack", {}).get("run", {}).get("run_id")
        or packs.get("editorial_memo", {}).get("run_id")
        or "fixture-run"
    )


def _prepare_run_dir(run_dir: Path) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    for child in ("charts", "render", "qa", "publish"):
        target = run_dir / child
        if target.exists():
            shutil.rmtree(target)
    for filename in (*PACK_FILES.values(), "manifest.json"):
        target = run_dir / filename
        if target.exists():
            target.unlink()


def _copy_inputs(fixture_dir: Path, run_dir: Path) -> None:
    for filename in PACK_FILES.values():
        shutil.copy2(fixture_dir / filename, run_dir / filename)


def _publish_files_with_integrity(run_dir: Path, files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    enriched_files: list[dict[str, Any]] = []
    for item in files:
        enriched = dict(item)
        path = run_dir / str(item.get("local_path"))
        if path.exists():
            enriched["sha256"] = _sha256(path)
            enriched["bytes"] = path.stat().st_size
        enriched_files.append(enriched)
    return enriched_files


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
