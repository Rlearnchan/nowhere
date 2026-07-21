from __future__ import annotations

import argparse
from pathlib import Path

from .approval import approval_status, approve_run, reject_run
from .audit import audit_run
from .collect import collect_fixture_sources
from .collected import build_collected_bundle
from .execution_status import summarize_execution_status
from .phase0 import build_fixture_bundle
from .publish import build_publish_dry_run
from .source_audit import audit_adapter_outputs
from .cpanel import probe_cpanel, publish_cpanel, verify_public_urls
from .datawrapper import plan_datawrapper, probe_datawrapper, verify_datawrapper_urls

TEMPLATE = """# {date} 시황 라이브 참고 자료

- 제목: {title}
- 작성 상태: draft
- 확인 기준 시각(KST): 

## 오늘의 핵심 흐름

- 

## 꼭 확인할 지표

| 항목 | 수치/상태 | 출처 | 메모 |
|---|---:|---|---|

## 링크 큐

| 상태 | 제목 | URL | 사용 메모 |
|---|---|---|---|

## 방송용 포인트

1. 

## 리스크/확인 필요

- 
"""


def init_day(root: Path, date: str, title: str) -> Path:
    day_dir = root / "references" / date
    day_dir.mkdir(parents=True, exist_ok=True)
    for name in ("links.md", "market_brief.md", "talking_points.md", "source_notes.md"):
        path = day_dir / name
        if not path.exists():
            path.write_text(f"# {date} {name}\n\n", encoding="utf-8")
    readme = day_dir / "README.md"
    if not readme.exists():
        readme.write_text(TEMPLATE.format(date=date, title=title), encoding="utf-8")
    return day_dir


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="nowhere")
    subparsers = parser.add_subparsers(dest="command")
    init = subparsers.add_parser("init-day", help="Create a daily live reference folder")
    init.add_argument("--root", type=Path, default=Path.cwd())
    init.add_argument("--date", required=True)
    init.add_argument("--title", default="")

    brief = subparsers.add_parser("brief", help="Build NOWHERE NOON BRIEF artifacts")
    brief_subparsers = brief.add_subparsers(dest="brief_command")
    fixture = brief_subparsers.add_parser(
        "build-fixture",
        help="Build a Phase 0 run bundle from fixture packs",
    )
    fixture.add_argument("--root", type=Path, default=Path.cwd())
    fixture.add_argument(
        "--fixture",
        type=Path,
        default=Path("demo/2026-07-14_1430"),
        help="Directory containing market_pack.json, news_pack.json, and editorial_memo.json",
    )
    fixture.add_argument("--run-id", default=None)
    fixture.add_argument("--output-root", type=Path, default=None)
    fixture.add_argument("--no-pdf", action="store_true", help="Skip local PDF rendering")

    collected = brief_subparsers.add_parser(
        "build-collected",
        help="Build a Phase 0 bundle from adapter_outputs market/news packs",
    )
    collected.add_argument("adapter_output_dir", type=Path)
    collected.add_argument("--root", type=Path, default=Path.cwd())
    collected.add_argument("--run-id", default=None)
    collected.add_argument("--output-root", type=Path, default=None)
    collected.add_argument("--editorial-memo", type=Path, default=None, help="Optional editorial_memo.json override")
    collected.add_argument("--editorial-mode", choices=["rules", "auto", "llm"], default="rules", help="Generate editorial memo with rules, LLM auto fallback, or required LLM")
    collected.add_argument("--editorial-model", default=None, help="Optional OpenAI model for LLM editorial memo drafting")
    collected.add_argument("--no-pdf", action="store_true", help="Skip local PDF rendering")

    publish = brief_subparsers.add_parser(
        "publish-dry-run",
        help="Attach a buykings.kr/cPanel dry-run plan to a Phase 0 run",
    )
    publish.add_argument("run_dir", type=Path)

    cpanel = brief_subparsers.add_parser(
        "publish-cpanel",
        help="Plan or execute a guarded cPanel upload for a Phase 0 run",
    )
    cpanel.add_argument("run_dir", type=Path)
    cpanel.add_argument("--execute", action="store_true", help="Actually call the cPanel API")
    cpanel.add_argument("--confirm-execute", default=None, help="Must match run_id when --execute is used")
    cpanel.add_argument("--force", action="store_true", help="Allow upload even when QA says public publication is blocked")
    cpanel.add_argument("--allow-reexecute", action="store_true", help="Allow a second execute after a completed execute result exists")

    cpanel_probe = brief_subparsers.add_parser(
        "cpanel-probe",
        help="Run a read-only cPanel API probe using orchestrator/env credentials",
    )

    approve = brief_subparsers.add_parser(
        "approve",
        help="Mark a run's editorial memo as approved and rebuild QA/publish artifacts",
    )
    approve.add_argument("run_dir", type=Path)
    approve.add_argument("--by", required=True, help="Approver name or account")
    approve.add_argument("--at", default=None, help="Approval timestamp, ISO date-time")
    approve.add_argument("--notes", default=None)
    approve.add_argument("--no-pdf", action="store_true", help="Skip local PDF rendering")

    reject = brief_subparsers.add_parser(
        "reject",
        help="Mark a run's editorial memo as rejected and rebuild QA/publish artifacts",
    )
    reject.add_argument("run_dir", type=Path)
    reject.add_argument("--by", required=True, help="Reviewer name or account")
    reject.add_argument("--notes", required=True)
    reject.add_argument("--at", default=None, help="Rejection timestamp, ISO date-time")

    status = brief_subparsers.add_parser("approval-status", help="Print run approval state")
    status.add_argument("run_dir", type=Path)

    datawrapper = brief_subparsers.add_parser(
        "datawrapper-plan",
        help="Plan or execute Datawrapper chart creation from generated chart specs",
    )
    datawrapper.add_argument("run_dir", type=Path)
    datawrapper.add_argument("--execute", action="store_true", help="Actually call the Datawrapper API")
    datawrapper.add_argument("--confirm-execute", default=None, help="Must match run_id when --execute is used")
    datawrapper.add_argument("--force", action="store_true", help="Allow chart publish when QA has review warnings after approval")
    datawrapper.add_argument("--allow-reexecute", action="store_true", help="Allow a second execute after a completed execute result exists")

    datawrapper_probe = brief_subparsers.add_parser(
        "datawrapper-probe",
        help="Run a read-only Datawrapper API probe using orchestrator/env credentials",
    )

    preflight = brief_subparsers.add_parser(
        "preflight",
        help="Write a guarded readiness audit for approval, charts, Datawrapper, and cPanel",
    )
    preflight.add_argument("run_dir", type=Path)
    preflight.add_argument("--force", action="store_true", help="Treat review-warning publication blocks as explicitly overridden")
    preflight.add_argument("--probe-live", action="store_true", help="Include read-only Datawrapper/cPanel API probes")

    verify_public = brief_subparsers.add_parser(
        "verify-public",
        help="Run read-only checks against the public buykings.kr URLs for a run",
    )
    verify_public.add_argument("run_dir", type=Path)

    verify_datawrapper = brief_subparsers.add_parser(
        "verify-datawrapper",
        help="Run read-only checks against published Datawrapper chart URLs for a run",
    )
    verify_datawrapper.add_argument("run_dir", type=Path)

    execution_status = brief_subparsers.add_parser(
        "execution-status",
        help="Summarize local approval, execute, and verification artifacts for a run",
    )
    execution_status.add_argument("run_dir", type=Path)

    source_audit = brief_subparsers.add_parser(
        "source-audit",
        help="Audit adapter observations for staleness, quality flags, and rights warnings",
    )
    source_audit.add_argument("adapter_output_dir", type=Path)
    source_audit.add_argument("--stale-hours", type=int, default=24)

    collect = brief_subparsers.add_parser(
        "collect-fixtures",
        help="Collect fixture source adapter outputs into draft market/news packs",
    )
    collect.add_argument("--root", type=Path, default=Path.cwd())
    collect.add_argument("--run-id", required=True)
    collect.add_argument("--output-root", type=Path, default=None)
    collect.add_argument("--jibi", type=Path, default=None)
    collect.add_argument("--naver", type=Path, action="append", default=None)
    collect.add_argument("--naver-url", action="append", default=None, help="Explicit Naver prototype URL; enables live Naver fetch")
    collect.add_argument("--yfinance", type=Path, default=None)
    collect.add_argument("--live-yfinance", action="store_true", help="Fetch yfinance live data instead of fixture JSON")
    collect.add_argument("--yfinance-ticker", action="append", default=None)
    collect.add_argument("--live-krx", action="store_true", help="Fetch KRX official index data instead of Naver prototype fixtures")
    collect.add_argument("--krx-bas-dd", default=None, help="KRX base date in YYYYMMDD; omit to auto-search recent Korean weekdays")
    collect.add_argument("--krx-market", action="append", default=None, help="KRX market to fetch, e.g. KOSPI or KOSDAQ")
    collect.add_argument("--krx-lookback-days", type=int, default=10, help="Recent weekday search window when --krx-bas-dd is omitted")
    collect.add_argument("--live-featured-stocks", action="store_true", help="Fetch Naver stock snapshots for tickers discovered from jibi news")
    collect.add_argument("--featured-stock-ticker", action="append", default=None, help="Explicit featured stock ticker to snapshot via Naver")
    collect.add_argument("--naver-stock", type=Path, action="append", default=None, help="Naver stock snapshot fixture JSON")
    collect.add_argument("--featured-stock-limit", type=int, default=5, help="Maximum featured stock snapshots to collect")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "init-day":
        print(init_day(args.root, args.date, args.title))
        return 0
    if args.command == "brief" and args.brief_command == "build-fixture":
        fixture_dir = args.fixture
        if not fixture_dir.is_absolute():
            fixture_dir = args.root / fixture_dir
        result = build_fixture_bundle(
            repo_root=args.root,
            fixture_dir=fixture_dir,
            run_id=args.run_id,
            output_root=args.output_root,
            render_pdf=not args.no_pdf,
        )
        print(result.run_dir)
        return 0
    if args.command == "brief" and args.brief_command == "build-collected":
        result = build_collected_bundle(
            repo_root=args.root,
            adapter_output_dir=args.adapter_output_dir,
            run_id=args.run_id,
            output_root=args.output_root,
            editorial_memo_path=args.editorial_memo,
            render_pdf=not args.no_pdf,
            editorial_mode=args.editorial_mode,
            editorial_model=args.editorial_model,
        )
        print(result.run_dir)
        return 0
    if args.command == "brief" and args.brief_command == "publish-dry-run":
        result = build_publish_dry_run(args.run_dir)
        print(result.manifest_path)
        return 0
    if args.command == "brief" and args.brief_command == "publish-cpanel":
        result = publish_cpanel(args.run_dir, execute=args.execute, force=args.force, confirm_execute=args.confirm_execute, allow_reexecute=args.allow_reexecute)
        print(args.run_dir / "publish" / "cpanel_publish_result.json")
        return 1 if result.get("mode") == "blocked" else 0
    if args.command == "brief" and args.brief_command == "cpanel-probe":
        result = probe_cpanel()
        print(result["status"])
        return 0 if result.get("status") == "ok" else 1
    if args.command == "brief" and args.brief_command == "approve":
        print(approve_run(args.run_dir, args.by, args.at, args.notes, render_pdf=not args.no_pdf))
        return 0
    if args.command == "brief" and args.brief_command == "reject":
        print(reject_run(args.run_dir, args.by, args.notes, args.at))
        return 0
    if args.command == "brief" and args.brief_command == "approval-status":
        status = approval_status(args.run_dir)
        print(status.get("status", "draft"))
        return 0
    if args.command == "brief" and args.brief_command == "datawrapper-plan":
        plan_datawrapper(args.run_dir, execute=args.execute, confirm_execute=args.confirm_execute, force=args.force, allow_reexecute=args.allow_reexecute)
        print(args.run_dir / "publish" / "datawrapper_plan.json")
        return 0
    if args.command == "brief" and args.brief_command == "datawrapper-probe":
        result = probe_datawrapper()
        print(result["status"])
        return 0 if result.get("status") == "ok" else 1
    if args.command == "brief" and args.brief_command == "preflight":
        report = audit_run(args.run_dir, force=args.force, probe_live=args.probe_live)
        print(args.run_dir / "publish" / "preflight_report.json")
        return 0 if report["ready"] else 1
    if args.command == "brief" and args.brief_command == "verify-public":
        result = verify_public_urls(args.run_dir)
        print(args.run_dir / "publish" / "public_url_verification.json")
        return 0 if result.get("status") == "ok" else 1
    if args.command == "brief" and args.brief_command == "verify-datawrapper":
        result = verify_datawrapper_urls(args.run_dir)
        print(args.run_dir / "publish" / "datawrapper_public_url_verification.json")
        return 0 if result.get("status") == "ok" else 1
    if args.command == "brief" and args.brief_command == "execution-status":
        result = summarize_execution_status(args.run_dir)
        print(args.run_dir / "publish" / "execution_status.json")
        return 0 if result.get("complete") else 1
    if args.command == "brief" and args.brief_command == "source-audit":
        result = audit_adapter_outputs(args.adapter_output_dir, stale_hours=args.stale_hours)
        print(args.adapter_output_dir / "source_audit.json")
        return 0 if result.get("status") != "blocked" else 1
    if args.command == "brief" and args.brief_command == "collect-fixtures":
        out_dir = collect_fixture_sources(
            repo_root=args.root,
            run_id=args.run_id,
            output_root=args.output_root,
            jibi_path=args.jibi,
            naver_paths=args.naver,
            yfinance_path=args.yfinance,
            live_yfinance=args.live_yfinance,
            yfinance_tickers=args.yfinance_ticker,
            naver_urls=args.naver_url,
            live_krx=args.live_krx,
            krx_bas_dd=args.krx_bas_dd,
            krx_markets=args.krx_market,
            krx_lookback_days=args.krx_lookback_days,
            live_featured_stocks=args.live_featured_stocks,
            featured_stock_tickers=args.featured_stock_ticker,
            naver_stock_paths=args.naver_stock,
            featured_stock_limit=args.featured_stock_limit,
        )
        print(out_dir)
        return 0
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
