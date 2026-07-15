import json

import pytest
from pathlib import Path

from nowhere.audit import audit_run
from nowhere.chart_contracts import validate_chart_files, validate_chart_payloads
from nowhere.collect import collect_fixture_sources
from nowhere.collected import build_collected_bundle, draft_editorial_memo
from nowhere.contracts import load_json, validate_contract
from nowhere.phase0 import build_fixture_bundle
from nowhere.publish import build_publish_dry_run
from nowhere import cpanel as cpanel_module
from nowhere import datawrapper as datawrapper_module
from nowhere.cpanel import CpanelClient, _cpanel_response_verdict, probe_cpanel, publish_cpanel, verify_public_urls
from nowhere.approval import approval_snapshot_status, approve_run
from nowhere.datawrapper import DatawrapperClient, chart_to_csv, plan_datawrapper, probe_datawrapper, verify_datawrapper_urls
from nowhere.execution_status import summarize_execution_status
from nowhere.sources.base import RawArtifact, SourceRequest
from nowhere.sources.jibi import JibiJsonlAdapter
from nowhere.sources.naver_snapshot import NaverSnapshotAdapter
from nowhere.sources.yfinance_adapter import YFinanceAdapter
from nowhere.source_audit import audit_adapter_outputs


def complete_datawrapper_for_cpanel(run_dir: Path, env_path: Path, run_id: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(DatawrapperClient, "create_and_upload", lambda self, chart: {
        "chart_id": chart["chart_id"],
        "datawrapper_id": f"dw-{chart['chart_id']}",
        "status": "ok",
        "published": True,
        "public_url": f"https://datawrapper.dwcdn.net/dw-{chart['chart_id']}/1/",
    })
    monkeypatch.setattr(datawrapper_module, "_check_datawrapper_public_url", lambda chart: {
        "chart_id": chart.get("chart_id"),
        "datawrapper_id": chart.get("datawrapper_id"),
        "url": chart.get("public_url"),
        "status": "ok",
        "http_status": 200,
        "bytes_checked": 128,
        "error": None,
    })
    plan_datawrapper(run_dir, execute=True, confirm_execute=run_id, force=True, env_paths=(env_path,))
    verify_datawrapper_urls(run_dir)


def test_market_pack_contract_accepts_demo() -> None:
    root = Path(__file__).resolve().parents[1]
    data = load_json(root / "demo/2026-07-14_1430/market_pack.json")
    schema = load_json(root / "contracts/market_pack.schema.json")
    assert validate_contract(data, schema) == []


def test_contract_validation_rejects_missing_required_field() -> None:
    root = Path(__file__).resolve().parents[1]
    data = load_json(root / "demo/2026-07-14_1430/news_pack.json")
    schema = load_json(root / "contracts/news_pack.schema.json")
    del data["events"][0]["title"]
    issues = validate_contract(data, schema)
    assert any("missing required property 'title'" in issue.message for issue in issues)


def test_build_fixture_bundle_creates_publish_artifacts(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    result = build_fixture_bundle(
        repo_root=root,
        fixture_dir=root / "demo/2026-07-14_1430",
        run_id="test-run",
        output_root=tmp_path,
        render_pdf=False,
    )

    assert result.manifest_path.exists()
    assert result.validation_report_path.exists()
    assert result.html_path.exists()
    assert (result.run_dir / "market_pack.json").exists()
    assert (result.run_dir / "charts/datawrapper_specs.json").exists()
    assert (result.run_dir / "charts/lightweight_series.json").exists()
    assert (result.run_dir / "publish/article.json").exists()
    assert (result.run_dir / "publish/publish_manifest.json").exists()
    publish_manifest = load_json(result.run_dir / "publish/publish_manifest.json")
    required_entries = [item for item in publish_manifest["files"] if not item.get("optional")]
    assert all(item.get("sha256") for item in required_entries)
    assert all(item.get("bytes") is not None for item in required_entries)
    assert (result.run_dir / "publish/site/index.html").exists()
    assert (result.run_dir / "publish/site/chart_bootstrap.js").exists()
    assert (result.run_dir / "publish/data/datawrapper_specs.json").exists()
    assert result.pdf_path is None

    report = load_json(result.validation_report_path)
    assert report["status"] == "review_needed"
    assert report["public_publish_allowed"] is False
    assert report["evidence_validation"]["missing_evidence_ids"] == []

    html = result.html_path.read_text(encoding="utf-8")
    assert "지수는 복원됐지만" in html
    assert "Public publish allowed" in html
    assert "nowhere-lightweight-chart" in html
    assert "chart_bootstrap.js" in html


def test_publish_dry_run_reads_env_without_secrets(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    result = build_fixture_bundle(
        repo_root=root,
        fixture_dir=root / "demo/2026-07-14_1430",
        run_id="publish-test",
        output_root=tmp_path,
        render_pdf=False,
    )
    env_path = tmp_path / "test.env"
    env_path.write_text(
        "CPANEL_HOST=example.com\n"
        "CPANEL_USER=user\n"
        "CPANEL_TOKEN=secret-token\n"
        "CPANEL_DOCROOT=/home/user/public_html\n",
        encoding="utf-8",
    )

    dry_run = build_publish_dry_run(result.run_dir, env_paths=(env_path,))
    manifest = load_json(dry_run.manifest_path)

    assert dry_run.configured is True
    assert manifest["publisher"]["configured"] is True
    assert manifest["publisher"]["env"]["CPANEL_TOKEN"] is True
    assert "secret-token" not in dry_run.manifest_path.read_text(encoding="utf-8")


def test_cpanel_publish_plan_blocks_unapproved_run(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    result = build_fixture_bundle(
        repo_root=root,
        fixture_dir=root / "demo/2026-07-14_1430",
        run_id="cpanel-test",
        output_root=tmp_path,
        render_pdf=False,
    )
    env_path = tmp_path / "test.env"
    env_path.write_text(
        "CPANEL_HOST=example.com\n"
        "CPANEL_USER=user\n"
        "CPANEL_TOKEN=secret-token\n"
        "CPANEL_DOCROOT=/home/user/public_html\n"
        "CPANEL_DATA_DIR=/home/user/public-data\n",
        encoding="utf-8",
    )
    build_publish_dry_run(result.run_dir, env_paths=(env_path,))

    publish_result = publish_cpanel(result.run_dir, env_paths=(env_path,))
    result_text = (result.run_dir / "publish/cpanel_publish_result.json").read_text(encoding="utf-8")

    assert publish_result["blocked"] is True
    assert "approval status is not approved" in publish_result["blocked_reasons"][0]
    assert "secret-token" not in result_text
    assert any(item["remote_role"] == "article_html" for item in publish_result["files"])


def test_approved_run_allows_forced_cpanel_plan(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    result = build_fixture_bundle(
        repo_root=root,
        fixture_dir=root / "demo/2026-07-14_1430",
        run_id="approved-cpanel-test",
        output_root=tmp_path,
        render_pdf=False,
    )
    env_path = tmp_path / "test.env"
    env_path.write_text(
        "CPANEL_HOST=example.com\n"
        "CPANEL_USER=user\n"
        "CPANEL_TOKEN=secret-token\n"
        "CPANEL_DOCROOT=/home/user/public_html\n"
        "CPANEL_DATA_DIR=/home/user/public-data\n",
        encoding="utf-8",
    )

    approve_run(
        result.run_dir,
        approved_by="tester",
        approved_at="2026-07-14T15:00:00+09:00",
        render_pdf=False,
    )
    build_publish_dry_run(result.run_dir, env_paths=(env_path,))

    blocked_without_force = publish_cpanel(result.run_dir, env_paths=(env_path,))
    forced_plan = publish_cpanel(result.run_dir, force=True, env_paths=(env_path,))
    report = load_json(result.run_dir / "qa/validation_report.json")

    assert report["approval"]["status"] == "approved"
    assert blocked_without_force["blocked"] is True
    assert forced_plan["blocked"] is False
    assert forced_plan["approval_status"] == "approved"




def test_publish_bundle_exposes_lightweight_frontend_bootstrap(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    result = build_fixture_bundle(
        repo_root=root,
        fixture_dir=root / "demo/2026-07-14_1430",
        run_id="lightweight-frontend-test",
        output_root=tmp_path,
        render_pdf=False,
    )

    article = load_json(result.run_dir / "publish/article.json")
    manifest = load_json(result.run_dir / "publish/publish_manifest.json")
    bootstrap = (result.run_dir / "publish/site/chart_bootstrap.js").read_text(encoding="utf-8")

    assert article["artifacts"]["lightweight_bootstrap"] == "site/chart_bootstrap.js"
    assert any(item["remote_role"] == "article_asset" for item in manifest["files"])
    assert "lightweight-charts" in bootstrap
    assert "data/lightweight_series.json" in bootstrap

def test_chart_payload_contracts_are_structured_for_frontends(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    result = build_fixture_bundle(
        repo_root=root,
        fixture_dir=root / "demo/2026-07-14_1430",
        run_id="chart-contract-test",
        output_root=tmp_path,
        render_pdf=False,
    )

    datawrapper = load_json(result.run_dir / "charts/datawrapper_specs.json")
    lightweight = load_json(result.run_dir / "charts/lightweight_series.json")

    assert datawrapper["schema_version"] == "nowhere.datawrapper_specs.v1"
    assert datawrapper["charts"][0]["table"]["columns"]
    assert datawrapper["charts"][0]["metadata"]["source_ids"]
    assert lightweight["schema_version"] == "nowhere.lightweight_series.v1"
    assert lightweight["charts"][0]["series"][0]["type"] == "Candlestick"
    assert datawrapper["charts"][0]["table"]["rows"][0]["redistribution_allowed"] in {True, False}
    assert "redistribution_allowed" in datawrapper["charts"][0]["table"]["columns"]
    assert "redistribution_allowed" in lightweight["charts"][0]["series"][0]["metadata"]
    chart_issues = validate_chart_files(result.run_dir, root / "contracts")
    assert chart_issues == {"datawrapper_specs": [], "lightweight_series": []}
    qa_report = load_json(result.run_dir / "qa/validation_report.json")
    assert qa_report["contract_validation"]["datawrapper_specs"] == []
    assert qa_report["contract_validation"]["lightweight_series"] == []


def test_chart_contract_validation_flags_frontend_breaking_payloads(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    result = build_fixture_bundle(
        repo_root=root,
        fixture_dir=root / "demo/2026-07-14_1430",
        run_id="chart-contract-invalid-test",
        output_root=tmp_path,
        render_pdf=False,
    )
    datawrapper_path = result.run_dir / "charts/datawrapper_specs.json"
    datawrapper = load_json(datawrapper_path)
    del datawrapper["charts"][0]["table"]["rows"][0]["market"]
    datawrapper_path.write_text(json.dumps(datawrapper), encoding="utf-8")

    lightweight_path = result.run_dir / "charts/lightweight_series.json"
    lightweight = load_json(lightweight_path)
    lightweight["charts"][0]["series"][0]["data"][0]["close"] = "bad"
    lightweight_path.write_text(json.dumps(lightweight), encoding="utf-8")

    issues = validate_chart_files(result.run_dir, root / "contracts")
    report = audit_run(result.run_dir, env_paths=(tmp_path / "missing.env",))

    assert issues["datawrapper_specs"]
    assert issues["lightweight_series"]
    assert report["chart_contracts"]["valid"] is False
    assert "chart payload contract validation has errors" in report["blockers"]


def test_source_adapters_normalize_fixture_inputs() -> None:
    root = Path(__file__).resolve().parents[1]

    jibi = JibiJsonlAdapter(root / "fixtures/jibi/sample_events.jsonl")
    jibi_raw = jibi.fetch(SourceRequest(source_id="src-jibi"))
    jibi_obs = jibi.normalize(jibi_raw)
    assert jibi.healthcheck().status == "ok"
    assert jibi_obs[0].field_name == "news_event"
    assert "missing_market_links" in jibi_obs[0].quality_flags
    assert "missing_reported_claims" in jibi_obs[0].quality_flags
    assert "low_significance_hint" in jibi_obs[0].quality_flags
    assert "unverified_news_event" in jibi_obs[0].quality_flags

    naver = NaverSnapshotAdapter(root / "fixtures/naver/kospi_snapshot.json")
    naver_raw = naver.fetch(SourceRequest(source_id="src-naver-fixture"))
    naver_obs = naver.normalize(naver_raw)
    assert naver.healthcheck().status == "ok"
    assert "prototype_only" in naver_obs[0].quality_flags
    assert "redistribution_restricted" in naver_obs[0].quality_flags
    assert naver_obs[0].rights_class == "public_web_restricted"

    naver_html = NaverSnapshotAdapter(root / "fixtures/naver/kospi_snapshot.html")
    naver_html_obs = naver_html.normalize(naver_html.fetch(SourceRequest(source_id="src-naver-html")))
    assert naver_html_obs[0].observation_id == "mkt-kospi-html-fixture"

    yfinance = YFinanceAdapter()
    raw = RawArtifact(
        source_id="src-yfinance-fixture",
        captured_at="2026-07-14T00:00:00+00:00",
        payload=(root / "fixtures/yfinance/global_prices.json").read_text(encoding="utf-8"),
        content_type="application/json",
        rights_class="open_source_adapter",
    )
    yf_obs = yfinance.normalize(raw)
    assert yfinance.healthcheck().status in {"ok", "review_needed"}
    assert yf_obs[0].field_name == "global_price_latest"
    assert round(yf_obs[0].value["change_pct_from_window_start"], 6) == 1.0
    assert yf_obs[0].value["window_start"] == "2026-07-13T09:30:00+00:00"
    assert yf_obs[0].value["window_end"] == "2026-07-13T16:00:00+00:00"
    assert yf_obs[0].value["point_count"] == 2
    assert yf_obs[0].quality_flags == ["yahoo_terms_review_required"]


def test_datawrapper_plan_exports_csv_preview(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    result = build_fixture_bundle(
        repo_root=root,
        fixture_dir=root / "demo/2026-07-14_1430",
        run_id="datawrapper-test",
        output_root=tmp_path,
        render_pdf=False,
    )
    env_path = tmp_path / "test.env"
    env_path.write_text("DATAWRAPPER_ACCESS_TOKEN=secret-token\n", encoding="utf-8")

    plan = plan_datawrapper(result.run_dir, env_paths=(env_path,))
    plan_text = (result.run_dir / "publish/datawrapper_plan.json").read_text(encoding="utf-8")
    first_chart = load_json(result.run_dir / "charts/datawrapper_specs.json")["charts"][0]

    assert plan["configured"] is True
    assert plan["charts"][0]["rows"] >= 1
    assert "secret-token" not in plan_text
    assert "market" in chart_to_csv(first_chart).splitlines()[0]


def test_collect_fixture_sources_writes_contract_valid_draft_packs(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    out_dir = collect_fixture_sources(root, "collect-test", output_root=tmp_path)

    market = load_json(out_dir / "market_pack.json")
    news = load_json(out_dir / "news_pack.json")
    validation = load_json(out_dir / "validation.json")
    source_audit = load_json(out_dir / "source_audit.json")

    assert validation["market_pack"] == []
    assert validation["news_pack"] == []
    assert len(market["indices"]) == 2
    assert len(market["global_context"]) == 2
    assert market["sources"][0]["rights_class"] == "public_web_restricted"
    assert market["indices"][0]["rights_class"] == "public_web_restricted"
    assert market["indices"][0]["prototype_only"] is True
    assert market["indices"][0]["redistribution_allowed"] is False
    assert "redistribution_restricted" in market["indices"][0]["quality_flags"]
    assert source_audit["status"] == "review_needed"
    assert source_audit["summary"]["restricted_rights_count"] >= 1
    assert source_audit["summary"]["quality_flagged_count"] >= 1
    assert news["events"][0]["event_id"] == "evt-sample"
    assert (out_dir / "observations/observations.json").exists()


def test_execute_paths_require_run_id_confirmation(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    result = build_fixture_bundle(
        repo_root=root,
        fixture_dir=root / "demo/2026-07-14_1430",
        run_id="execute-confirm-test",
        output_root=tmp_path,
        render_pdf=False,
    )
    env_path = tmp_path / "test.env"
    env_path.write_text(
        "CPANEL_HOST=example.com\n"
        "CPANEL_USER=user\n"
        "CPANEL_TOKEN=secret-token\n"
        "CPANEL_DOCROOT=/home/user/public_html\n"
        "CPANEL_DATA_DIR=/home/user/public-data\n"
        "DATAWRAPPER_ACCESS_TOKEN=dw-secret\n",
        encoding="utf-8",
    )
    approve_run(result.run_dir, approved_by="tester", approved_at="2026-07-14T15:00:00+09:00", render_pdf=False)
    build_publish_dry_run(result.run_dir, env_paths=(env_path,))

    cpanel_result = publish_cpanel(result.run_dir, execute=True, force=True, env_paths=(env_path,))
    dw_result = plan_datawrapper(result.run_dir, execute=True, env_paths=(env_path,))

    assert cpanel_result["mode"] == "blocked"
    assert "execute confirmation does not match run_id" in cpanel_result["blocked_reasons"]
    assert dw_result["mode"] == "blocked"
    assert "execute confirmation does not match run_id" in dw_result["blocked_reasons"]


def test_publish_dry_run_includes_public_urls(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    result = build_fixture_bundle(
        repo_root=root,
        fixture_dir=root / "demo/2026-07-14_1430",
        run_id="public-url-test",
        output_root=tmp_path,
        render_pdf=False,
    )
    env_path = tmp_path / "test.env"
    env_path.write_text(
        "CPANEL_HOST=example.com\n"
        "CPANEL_USER=user\n"
        "CPANEL_TOKEN=secret-token\n"
        "CPANEL_DOCROOT=public_html/tracker\n"
        "CPANEL_DATA_DIR=public-data\n",
        encoding="utf-8",
    )

    build_publish_dry_run(result.run_dir, env_paths=(env_path,))
    manifest = load_json(result.run_dir / "publish/publish_manifest.json")

    assert manifest["publisher"]["remote_plan"]["public_url"] == "https://buykings.kr/tracker/nowhere/public-url-test/"
    assert manifest["publisher"]["remote_plan"]["public_pdf_url"].endswith("/brief.pdf")


def test_cpanel_execute_blocks_publish_file_hash_mismatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = Path(__file__).resolve().parents[1]
    result = build_fixture_bundle(
        repo_root=root,
        fixture_dir=root / "demo/2026-07-14_1430",
        run_id="cpanel-hash-gate-test",
        output_root=tmp_path,
        render_pdf=False,
    )
    env_path = tmp_path / "test.env"
    env_path.write_text(
        "CPANEL_HOST=example.com\n"
        "CPANEL_USER=user\n"
        "CPANEL_TOKEN=secret-token\n"
        "CPANEL_DOCROOT=public_html/tracker\n"
        "CPANEL_DATA_DIR=public-data\n"
        "DATAWRAPPER_ACCESS_TOKEN=dw-secret\n",
        encoding="utf-8",
    )
    approve_run(result.run_dir, approved_by="tester", approved_at="2026-07-14T15:00:00+09:00", render_pdf=False)
    build_publish_dry_run(result.run_dir, env_paths=(env_path,))
    complete_datawrapper_for_cpanel(result.run_dir, env_path, "cpanel-hash-gate-test", monkeypatch)
    index_path = result.run_dir / "publish/site/index.html"
    index_path.write_text(index_path.read_text(encoding="utf-8") + "\n<!-- tampered -->\n", encoding="utf-8")
    monkeypatch.setattr(CpanelClient, "upload_file", lambda self, local_path, remote_dir: {"local_path": local_path, "remote_dir": remote_dir, "status": "ok", "http_status": 200})

    blocked = publish_cpanel(
        result.run_dir,
        execute=True,
        force=True,
        confirm_execute="cpanel-hash-gate-test",
        env_paths=(env_path,),
    )

    assert blocked["mode"] == "blocked"
    assert "one or more publish file hashes do not match manifest" in blocked["blocked_reasons"]
    html_entry = next(item for item in blocked["files"] if item["local_path"] == "publish/site/index.html")
    assert html_entry["hash_mismatch"] is True
    assert html_entry["expected_sha256"] != html_entry["sha256"]


def test_cpanel_execute_requires_datawrapper_publish_and_verify(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = Path(__file__).resolve().parents[1]
    result = build_fixture_bundle(
        repo_root=root,
        fixture_dir=root / "demo/2026-07-14_1430",
        run_id="cpanel-requires-dw-test",
        output_root=tmp_path,
        render_pdf=False,
    )
    env_path = tmp_path / "test.env"
    env_path.write_text(
        "CPANEL_HOST=example.com\n"
        "CPANEL_USER=user\n"
        "CPANEL_TOKEN=secret-token\n"
        "CPANEL_DOCROOT=public_html/tracker\n"
        "CPANEL_DATA_DIR=public-data\n"
        "DATAWRAPPER_ACCESS_TOKEN=dw-secret\n",
        encoding="utf-8",
    )
    approve_run(result.run_dir, approved_by="tester", approved_at="2026-07-14T15:00:00+09:00", render_pdf=False)
    build_publish_dry_run(result.run_dir, env_paths=(env_path,))
    monkeypatch.setattr(CpanelClient, "upload_file", lambda self, local_path, remote_dir: {"local_path": local_path, "remote_dir": remote_dir, "status": "ok", "http_status": 200})

    blocked = publish_cpanel(
        result.run_dir,
        execute=True,
        force=True,
        confirm_execute="cpanel-requires-dw-test",
        env_paths=(env_path,),
    )
    assert blocked["mode"] == "blocked"
    assert "Datawrapper execute and URL verification must complete before cPanel execute" in blocked["blocked_reasons"]
    assert blocked["datawrapper_dependency"]["required"] is True
    assert blocked["datawrapper_dependency"]["ready_for_cpanel"] is False

    complete_datawrapper_for_cpanel(result.run_dir, env_path, "cpanel-requires-dw-test", monkeypatch)
    allowed_plan = publish_cpanel(result.run_dir, force=True, env_paths=(env_path,))
    assert allowed_plan["datawrapper_dependency"]["ready_for_cpanel"] is True


def test_cpanel_execute_revalidates_chart_contracts_after_datawrapper(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = Path(__file__).resolve().parents[1]
    result = build_fixture_bundle(
        repo_root=root,
        fixture_dir=root / "demo/2026-07-14_1430",
        run_id="cpanel-chart-gate-test",
        output_root=tmp_path,
        render_pdf=False,
    )
    env_path = tmp_path / "test.env"
    env_path.write_text(
        "CPANEL_HOST=example.com\n"
        "CPANEL_USER=user\n"
        "CPANEL_TOKEN=secret-token\n"
        "CPANEL_DOCROOT=public_html/tracker\n"
        "CPANEL_DATA_DIR=public-data\n"
        "DATAWRAPPER_ACCESS_TOKEN=dw-secret\n",
        encoding="utf-8",
    )
    approve_run(result.run_dir, approved_by="tester", approved_at="2026-07-14T15:00:00+09:00", render_pdf=False)
    build_publish_dry_run(result.run_dir, env_paths=(env_path,))
    complete_datawrapper_for_cpanel(result.run_dir, env_path, "cpanel-chart-gate-test", monkeypatch)
    datawrapper_path = result.run_dir / "charts/datawrapper_specs.json"
    datawrapper = load_json(datawrapper_path)
    del datawrapper["charts"][0]["table"]["rows"][0]["market"]
    datawrapper_path.write_text(json.dumps(datawrapper), encoding="utf-8")
    monkeypatch.setattr(CpanelClient, "upload_file", lambda self, local_path, remote_dir: {"local_path": local_path, "remote_dir": remote_dir, "status": "ok", "http_status": 200})

    result_payload = publish_cpanel(
        result.run_dir,
        execute=True,
        force=True,
        confirm_execute="cpanel-chart-gate-test",
        env_paths=(env_path,),
    )

    assert result_payload["mode"] == "blocked"
    assert "chart payload contract validation has errors" in result_payload["blocked_reasons"]
    assert result_payload["artifact_gate"]["chart_contracts"]["valid"] is False


def test_cpanel_execute_revalidates_source_audit_blockers_after_datawrapper(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = Path(__file__).resolve().parents[1]
    result = build_fixture_bundle(
        repo_root=root,
        fixture_dir=root / "demo/2026-07-14_1430",
        run_id="cpanel-source-gate-test",
        output_root=tmp_path,
        render_pdf=False,
    )
    env_path = tmp_path / "test.env"
    env_path.write_text(
        "CPANEL_HOST=example.com\n"
        "CPANEL_USER=user\n"
        "CPANEL_TOKEN=secret-token\n"
        "CPANEL_DOCROOT=public_html/tracker\n"
        "CPANEL_DATA_DIR=public-data\n"
        "DATAWRAPPER_ACCESS_TOKEN=dw-secret\n",
        encoding="utf-8",
    )
    approve_run(result.run_dir, approved_by="tester", approved_at="2026-07-14T15:00:00+09:00", render_pdf=False)
    build_publish_dry_run(result.run_dir, env_paths=(env_path,))
    complete_datawrapper_for_cpanel(result.run_dir, env_path, "cpanel-source-gate-test", monkeypatch)
    adapter_dir = result.run_dir / "adapter_outputs"
    obs_dir = adapter_dir / "observations"
    obs_dir.mkdir(parents=True)
    (obs_dir / "observations.json").write_text(
        json.dumps([{"observation_id":"yf","source_id":"src-yfinance","field_name":"global_price_latest","value":{},"unit":"price","as_of":"2026-07-14T00:00:00+00:00","quality_flags":[],"rights_class":"open_source_adapter"}]),
        encoding="utf-8",
    )
    (adapter_dir / "manifest.json").write_text(
        json.dumps({"adapter_contract": {"required_fields": ["news_event", "index_snapshot", "global_price_latest"]}}),
        encoding="utf-8",
    )
    audit_adapter_outputs(adapter_dir, stale_hours=999999)
    monkeypatch.setattr(CpanelClient, "upload_file", lambda self, local_path, remote_dir: {"local_path": local_path, "remote_dir": remote_dir, "status": "ok", "http_status": 200})

    result_payload = publish_cpanel(
        result.run_dir,
        execute=True,
        force=True,
        confirm_execute="cpanel-source-gate-test",
        env_paths=(env_path,),
    )

    assert result_payload["mode"] == "blocked"
    assert "source audit is blocked" in result_payload["blocked_reasons"]
    assert result_payload["artifact_gate"]["source_audit"]["status"] == "blocked"


def test_cpanel_execute_result_validation_with_fake_uploads(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = Path(__file__).resolve().parents[1]
    result = build_fixture_bundle(
        repo_root=root,
        fixture_dir=root / "demo/2026-07-14_1430",
        run_id="cpanel-execute-test",
        output_root=tmp_path,
        render_pdf=False,
    )
    env_path = tmp_path / "test.env"
    env_path.write_text(
        "CPANEL_HOST=example.com\n"
        "CPANEL_USER=user\n"
        "CPANEL_TOKEN=secret-token\n"
        "CPANEL_DOCROOT=public_html/tracker\n"
        "CPANEL_DATA_DIR=public-data\n"
        "DATAWRAPPER_ACCESS_TOKEN=dw-secret\n",
        encoding="utf-8",
    )
    approve_run(result.run_dir, approved_by="tester", approved_at="2026-07-14T15:00:00+09:00", render_pdf=False)
    build_publish_dry_run(result.run_dir, env_paths=(env_path,))

    def fake_upload(self: CpanelClient, local_path: str, remote_dir: str) -> dict[str, object]:
        return {"local_path": local_path, "remote_dir": remote_dir, "status": "ok", "http_status": 200}

    complete_datawrapper_for_cpanel(result.run_dir, env_path, "cpanel-execute-test", monkeypatch)
    monkeypatch.setattr(CpanelClient, "upload_file", fake_upload)
    monkeypatch.setattr(cpanel_module, "verify_public_urls", lambda run_dir: {"schema_version": "nowhere.public_url_verification.v1", "status": "ok", "checks": []})
    publish_result = publish_cpanel(
        result.run_dir,
        execute=True,
        force=True,
        confirm_execute="cpanel-execute-test",
        env_paths=(env_path,),
    )

    assert publish_result["mode"] == "execute"
    assert publish_result["validation"]["execute_complete"] is True
    assert publish_result["validation"]["failed_upload_count"] == 0


def test_datawrapper_execute_result_validation_with_fake_uploads(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = Path(__file__).resolve().parents[1]
    result = build_fixture_bundle(
        repo_root=root,
        fixture_dir=root / "demo/2026-07-14_1430",
        run_id="dw-execute-test",
        output_root=tmp_path,
        render_pdf=False,
    )
    env_path = tmp_path / "test.env"
    env_path.write_text("DATAWRAPPER_ACCESS_TOKEN=secret-token\n", encoding="utf-8")
    approve_run(result.run_dir, approved_by="tester", approved_at="2026-07-14T15:00:00+09:00", render_pdf=False)
    build_publish_dry_run(result.run_dir, env_paths=(env_path,))

    def fake_create_and_upload(self: DatawrapperClient, chart: dict[str, object]) -> dict[str, object]:
        return {
            "chart_id": chart["chart_id"],
            "datawrapper_id": f"dw-{chart['chart_id']}",
            "status": "ok",
            "published": True,
            "public_url": f"https://www.datawrapper.de/_/dw-{chart['chart_id']}/",
        }

    monkeypatch.setattr(DatawrapperClient, "create_and_upload", fake_create_and_upload)
    dw_result = plan_datawrapper(
        result.run_dir,
        execute=True,
        confirm_execute="dw-execute-test",
        force=True,
        env_paths=(env_path,),
    )

    assert dw_result["mode"] == "execute"
    assert dw_result["validation"]["execute_complete"] is True
    assert len(dw_result["validation"]["public_urls"]) == len(dw_result["charts"])
    article = load_json(result.run_dir / "publish/article.json")
    manifest = load_json(result.run_dir / "publish/publish_manifest.json")
    dw_publish_result = load_json(result.run_dir / "publish/data/datawrapper_result.json")
    assert article["artifacts"]["datawrapper_result"] == "data/datawrapper_result.json"
    assert len(article["datawrapper_public_urls"]) == len(dw_result["charts"])
    chart_result_entry = next(item for item in manifest["files"] if item["remote_role"] == "chart_result")
    assert chart_result_entry["sha256"]
    assert chart_result_entry["bytes"] > 0
    assert dw_publish_result["validation"]["execute_complete"] is True


def test_verify_datawrapper_urls_checks_published_chart_urls(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = Path(__file__).resolve().parents[1]
    result = build_fixture_bundle(
        repo_root=root,
        fixture_dir=root / "demo/2026-07-14_1430",
        run_id="dw-url-verify-test",
        output_root=tmp_path,
        render_pdf=False,
    )
    env_path = tmp_path / "test.env"
    env_path.write_text("DATAWRAPPER_ACCESS_TOKEN=secret-token\n", encoding="utf-8")
    approve_run(result.run_dir, approved_by="tester", approved_at="2026-07-14T15:00:00+09:00", render_pdf=False)
    build_publish_dry_run(result.run_dir, env_paths=(env_path,))

    monkeypatch.setattr(DatawrapperClient, "create_and_upload", lambda self, chart: {
        "chart_id": chart["chart_id"],
        "datawrapper_id": f"dw-{chart['chart_id']}",
        "status": "ok",
        "published": True,
        "public_url": f"https://datawrapper.dwcdn.net/dw-{chart['chart_id']}/1/",
    })
    plan_datawrapper(result.run_dir, execute=True, confirm_execute="dw-url-verify-test", force=True, env_paths=(env_path,))
    monkeypatch.setattr(datawrapper_module, "_check_datawrapper_public_url", lambda chart: {
        "chart_id": chart.get("chart_id"),
        "datawrapper_id": chart.get("datawrapper_id"),
        "url": chart.get("public_url"),
        "status": "ok",
        "http_status": 200,
        "bytes_checked": 128,
        "error": None,
    })

    verification = verify_datawrapper_urls(result.run_dir)
    saved = load_json(result.run_dir / "publish/datawrapper_public_url_verification.json")

    assert verification["status"] == "ok"
    assert verification["checked_url_count"] == len(verification["checks"])
    assert verification["expected_chart_count"] == len(load_json(result.run_dir / "charts/datawrapper_specs.json")["charts"])
    assert saved["status"] == "ok"


def test_datawrapper_execute_does_not_complete_without_publish_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = Path(__file__).resolve().parents[1]
    result = build_fixture_bundle(
        repo_root=root,
        fixture_dir=root / "demo/2026-07-14_1430",
        run_id="dw-incomplete-publish-test",
        output_root=tmp_path,
        render_pdf=False,
    )
    env_path = tmp_path / "test.env"
    env_path.write_text("DATAWRAPPER_ACCESS_TOKEN=secret-token\n", encoding="utf-8")
    approve_run(result.run_dir, approved_by="tester", approved_at="2026-07-14T15:00:00+09:00", render_pdf=False)
    build_publish_dry_run(result.run_dir, env_paths=(env_path,))

    def fake_create_and_upload(self: DatawrapperClient, chart: dict[str, object]) -> dict[str, object]:
        return {
            "chart_id": chart["chart_id"],
            "datawrapper_id": f"dw-{chart['chart_id']}",
            "status": "ok",
            "published": False,
            "public_url": None,
        }

    monkeypatch.setattr(DatawrapperClient, "create_and_upload", fake_create_and_upload)
    dw_result = plan_datawrapper(
        result.run_dir,
        execute=True,
        confirm_execute="dw-incomplete-publish-test",
        force=True,
        env_paths=(env_path,),
    )

    assert dw_result["validation"]["execute_complete"] is False
    assert dw_result["validation"]["published_count"] == 0
    assert dw_result["validation"]["missing_public_url_count"] == len(dw_result["charts"])
    assert not (result.run_dir / "publish/datawrapper_execute_result.json").exists()
    assert not (result.run_dir / "publish/data/datawrapper_result.json").exists()


def test_preflight_blocks_draft_and_passes_forced_approved_run(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    result = build_fixture_bundle(
        repo_root=root,
        fixture_dir=root / "demo/2026-07-14_1430",
        run_id="preflight-test",
        output_root=tmp_path,
        render_pdf=False,
    )
    env_path = tmp_path / "test.env"
    env_path.write_text(
        "CPANEL_HOST=example.com\n"
        "CPANEL_USER=user\n"
        "CPANEL_TOKEN=secret-token\n"
        "CPANEL_DOCROOT=public_html/tracker\n"
        "CPANEL_DATA_DIR=public-data\n"
        "DATAWRAPPER_ACCESS_TOKEN=dw-secret\n",
        encoding="utf-8",
    )
    build_publish_dry_run(result.run_dir, env_paths=(env_path,))

    draft_report = audit_run(result.run_dir, env_paths=(env_path,))
    assert draft_report["ready"] is False
    assert "approval status is not approved" in draft_report["blockers"]

    approve_run(result.run_dir, approved_by="tester", approved_at="2026-07-14T15:00:00+09:00", render_pdf=False)
    build_publish_dry_run(result.run_dir, env_paths=(env_path,))
    approved_report = audit_run(result.run_dir, force=True, env_paths=(env_path,))
    report_text = (result.run_dir / "publish/preflight_report.json").read_text(encoding="utf-8")

    assert approved_report["ready"] is True
    assert approved_report["approval"]["status"] == "approved"
    assert approved_report["cpanel"]["validation"]["ready_for_execute"] is True
    assert approved_report["datawrapper"]["validation"]["ready_for_execute"] is True
    assert approved_report["execution_plan"]["ready"] is True
    commands = [item["command"] for item in approved_report["execution_plan"]["commands"]]
    assert "verify-datawrapper" in commands[2]
    assert "execution-status" in commands[-1]
    assert commands[1].endswith("--execute --confirm-execute preflight-test --force")
    assert commands[3].endswith("--execute --confirm-execute preflight-test --force")
    assert "secret-token" not in report_text


def test_read_only_api_probes_redact_credentials(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_path = tmp_path / "test.env"
    env_path.write_text(
        "CPANEL_HOST=example.com\n"
        "CPANEL_USER=user\n"
        "CPANEL_TOKEN=secret-token\n"
        "CPANEL_DOCROOT=public_html/tracker\n"
        "DATAWRAPPER_ACCESS_TOKEN=dw-secret\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        CpanelClient,
        "probe_directory",
        lambda self, remote_dir: {
            "ok": True,
            "http_status": 200,
            "remote_dir_checked": remote_dir,
            "response_shape": {"type": "object", "keys": ["data"], "has_errors": False},
            "error": None,
        },
    )
    monkeypatch.setattr(
        DatawrapperClient,
        "probe_account",
        lambda self: {
            "ok": True,
            "http_status": 200,
            "account": {"id": "acct", "email_present": True, "name_present": True},
            "error": None,
        },
    )

    cpanel_probe = probe_cpanel(env_paths=(env_path,))
    dw_probe = probe_datawrapper(env_paths=(env_path,))

    assert cpanel_probe["status"] == "ok"
    assert dw_probe["status"] == "ok"
    assert "secret-token" not in str(cpanel_probe)
    assert "dw-secret" not in str(dw_probe)


def test_preflight_can_include_live_probe_results(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = Path(__file__).resolve().parents[1]
    result = build_fixture_bundle(
        repo_root=root,
        fixture_dir=root / "demo/2026-07-14_1430",
        run_id="preflight-probe-test",
        output_root=tmp_path,
        render_pdf=False,
    )
    env_path = tmp_path / "test.env"
    env_path.write_text(
        "CPANEL_HOST=example.com\n"
        "CPANEL_USER=user\n"
        "CPANEL_TOKEN=secret-token\n"
        "CPANEL_DOCROOT=public_html/tracker\n"
        "CPANEL_DATA_DIR=public-data\n"
        "DATAWRAPPER_ACCESS_TOKEN=dw-secret\n",
        encoding="utf-8",
    )
    approve_run(result.run_dir, approved_by="tester", approved_at="2026-07-14T15:00:00+09:00", render_pdf=False)
    build_publish_dry_run(result.run_dir, env_paths=(env_path,))
    monkeypatch.setattr(CpanelClient, "probe_directory", lambda self, remote_dir: {"ok": True, "http_status": 200, "remote_dir_checked": remote_dir, "error": None})
    monkeypatch.setattr(DatawrapperClient, "probe_account", lambda self: {"ok": True, "http_status": 200, "account": {"id": "acct"}, "error": None})

    report = audit_run(result.run_dir, force=True, probe_live=True, env_paths=(env_path,))

    assert report["ready"] is True
    assert report["probe_live"] is True
    assert report["cpanel"]["probe"]["status"] == "ok"
    assert report["datawrapper"]["probe"]["status"] == "ok"


def test_datawrapper_client_publishes_after_upload(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []
    client = DatawrapperClient(type("Config", (), {"access_token": "token", "api_base": "https://api.example.test"})())

    def fake_request(method: str, path: str, body: bytes, content_type: str) -> dict[str, object]:
        calls.append((method, path))
        if method == "POST" and path == "/charts":
            return {"id": "abc12"}
        if method == "PUT" and path == "/charts/abc12/data":
            return {"ok": True}
        if method == "POST" and path == "/charts/abc12/publish":
            return {"version": 1, "url": "//datawrapper.dwcdn.net/abc12/1/", "data": {"publishedAt": "2026-07-14 06:00:00"}}
        raise AssertionError((method, path))

    monkeypatch.setattr(client, "_request_json", fake_request)
    result = client.create_and_upload(
        {
            "chart_id": "local-chart",
            "title": "Chart",
            "chart_type": "d3-bars",
            "table": {"columns": ["name", "value"], "rows": [{"name": "A", "value": 1}]},
        }
    )

    assert calls == [("POST", "/charts"), ("PUT", "/charts/abc12/data"), ("POST", "/charts/abc12/publish")]
    assert result["published"] is True
    assert result["public_url"] == "https://datawrapper.dwcdn.net/abc12/1/"


def test_cpanel_execute_attaches_public_url_verification(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = Path(__file__).resolve().parents[1]
    result = build_fixture_bundle(
        repo_root=root,
        fixture_dir=root / "demo/2026-07-14_1430",
        run_id="cpanel-public-verify-test",
        output_root=tmp_path,
        render_pdf=False,
    )
    env_path = tmp_path / "test.env"
    env_path.write_text(
        "CPANEL_HOST=example.com\n"
        "CPANEL_USER=user\n"
        "CPANEL_TOKEN=secret-token\n"
        "CPANEL_DOCROOT=public_html/tracker\n"
        "CPANEL_DATA_DIR=public-data\n"
        "DATAWRAPPER_ACCESS_TOKEN=dw-secret\n",
        encoding="utf-8",
    )
    approve_run(result.run_dir, approved_by="tester", approved_at="2026-07-14T15:00:00+09:00", render_pdf=False)
    build_publish_dry_run(result.run_dir, env_paths=(env_path,))

    complete_datawrapper_for_cpanel(result.run_dir, env_path, "cpanel-public-verify-test", monkeypatch)
    monkeypatch.setattr(CpanelClient, "upload_file", lambda self, local_path, remote_dir: {"local_path": local_path, "remote_dir": remote_dir, "status": "ok", "http_status": 200})
    monkeypatch.setattr(cpanel_module, "verify_public_urls", lambda run_dir: {"schema_version": "nowhere.public_url_verification.v1", "status": "ok", "checks": []})

    publish_result = publish_cpanel(
        result.run_dir,
        execute=True,
        force=True,
        confirm_execute="cpanel-public-verify-test",
        env_paths=(env_path,),
    )

    assert publish_result["validation"]["execute_complete"] is True
    assert publish_result["validation"]["public_url_verified"] is True
    assert publish_result["public_url_verification"]["status"] == "ok"


def test_cpanel_execute_requires_successful_public_url_verification(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = Path(__file__).resolve().parents[1]
    result = build_fixture_bundle(
        repo_root=root,
        fixture_dir=root / "demo/2026-07-14_1430",
        run_id="cpanel-public-verify-fail-test",
        output_root=tmp_path,
        render_pdf=False,
    )
    env_path = tmp_path / "test.env"
    env_path.write_text(
        "CPANEL_HOST=example.com\n"
        "CPANEL_USER=user\n"
        "CPANEL_TOKEN=secret-token\n"
        "CPANEL_DOCROOT=public_html/tracker\n"
        "CPANEL_DATA_DIR=public-data\n"
        "DATAWRAPPER_ACCESS_TOKEN=dw-secret\n",
        encoding="utf-8",
    )
    approve_run(result.run_dir, approved_by="tester", approved_at="2026-07-14T15:00:00+09:00", render_pdf=False)
    build_publish_dry_run(result.run_dir, env_paths=(env_path,))
    complete_datawrapper_for_cpanel(result.run_dir, env_path, "cpanel-public-verify-fail-test", monkeypatch)
    monkeypatch.setattr(CpanelClient, "upload_file", lambda self, local_path, remote_dir: {"local_path": local_path, "remote_dir": remote_dir, "status": "ok", "http_status": 200})
    monkeypatch.setattr(cpanel_module, "verify_public_urls", lambda run_dir: {
        "schema_version": "nowhere.public_url_verification.v1",
        "status": "failed",
        "checks": [{"role": "html", "status": "failed", "http_status": 404}],
    })

    publish_result = publish_cpanel(
        result.run_dir,
        execute=True,
        force=True,
        confirm_execute="cpanel-public-verify-fail-test",
        env_paths=(env_path,),
    )

    assert publish_result["mode"] == "execute"
    assert publish_result["validation"]["execute_complete"] is False
    assert publish_result["validation"]["public_url_verified"] is False
    assert publish_result["validation"]["public_url_verification_status"] == "failed"
    assert "public URL verification failed after cPanel upload" in publish_result["post_upload_blockers"]
    assert not (result.run_dir / "publish/cpanel_execute_result.json").exists()

    status = summarize_execution_status(result.run_dir)
    assert status["complete"] is False
    assert status["external_writes_started"] is True
    assert status["cpanel"]["latest_mode"] == "execute"
    assert status["cpanel"]["latest_execute_complete"] is False
    assert status["cpanel"]["latest_post_upload_blockers"] == ["public URL verification failed after cPanel upload"]
    assert status["cpanel"]["execute_result_present"] is False


def test_execution_status_summarizes_complete_publish_flow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = Path(__file__).resolve().parents[1]
    result = build_fixture_bundle(
        repo_root=root,
        fixture_dir=root / "demo/2026-07-14_1430",
        run_id="execution-status-test",
        output_root=tmp_path,
        render_pdf=False,
    )
    env_path = tmp_path / "test.env"
    env_path.write_text(
        "CPANEL_HOST=example.com\n"
        "CPANEL_USER=user\n"
        "CPANEL_TOKEN=secret-token\n"
        "CPANEL_DOCROOT=public_html/tracker\n"
        "CPANEL_DATA_DIR=public-data\n"
        "DATAWRAPPER_ACCESS_TOKEN=dw-secret\n",
        encoding="utf-8",
    )
    approve_run(result.run_dir, approved_by="tester", approved_at="2026-07-14T15:00:00+09:00", render_pdf=False)
    build_publish_dry_run(result.run_dir, env_paths=(env_path,))
    audit_run(result.run_dir, force=True, env_paths=(env_path,))

    monkeypatch.setattr(DatawrapperClient, "create_and_upload", lambda self, chart: {
        "chart_id": chart["chart_id"],
        "datawrapper_id": f"dw-{chart['chart_id']}",
        "status": "ok",
        "published": True,
        "public_url": f"https://datawrapper.dwcdn.net/dw-{chart['chart_id']}/1/",
    })
    monkeypatch.setattr(datawrapper_module, "_check_datawrapper_public_url", lambda chart: {
        "chart_id": chart.get("chart_id"),
        "datawrapper_id": chart.get("datawrapper_id"),
        "url": chart.get("public_url"),
        "status": "ok",
        "http_status": 200,
        "bytes_checked": 128,
        "error": None,
    })
    monkeypatch.setattr(CpanelClient, "upload_file", lambda self, local_path, remote_dir: {"local_path": local_path, "remote_dir": remote_dir, "status": "ok", "http_status": 200})
    monkeypatch.setattr(cpanel_module, "verify_public_urls", lambda run_dir: {"schema_version": "nowhere.public_url_verification.v1", "status": "ok", "checks": []})

    plan_datawrapper(result.run_dir, execute=True, confirm_execute="execution-status-test", force=True, env_paths=(env_path,))
    verify_datawrapper_urls(result.run_dir)
    publish_cpanel(result.run_dir, execute=True, force=True, confirm_execute="execution-status-test", env_paths=(env_path,))
    (result.run_dir / "publish/public_url_verification.json").write_text(
        json.dumps({"schema_version": "nowhere.public_url_verification.v1", "status": "ok", "checks": []}),
        encoding="utf-8",
    )

    status = summarize_execution_status(result.run_dir)
    saved = load_json(result.run_dir / "publish/execution_status.json")

    assert status["complete"] is True
    assert status["external_writes_started"] is True
    assert status["datawrapper"]["public_urls_verified"] is True
    assert status["cpanel"]["public_urls_verified"] is True
    assert status["cpanel"]["latest_execute_complete"] is True
    assert status["datawrapper"]["latest_execute_complete"] is True
    assert saved["complete"] is True


def test_execute_results_are_preserved_and_block_reexecute(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = Path(__file__).resolve().parents[1]
    result = build_fixture_bundle(
        repo_root=root,
        fixture_dir=root / "demo/2026-07-14_1430",
        run_id="execute-ledger-test",
        output_root=tmp_path,
        render_pdf=False,
    )
    env_path = tmp_path / "test.env"
    env_path.write_text(
        "CPANEL_HOST=example.com\n"
        "CPANEL_USER=user\n"
        "CPANEL_TOKEN=secret-token\n"
        "CPANEL_DOCROOT=public_html/tracker\n"
        "CPANEL_DATA_DIR=public-data\n"
        "DATAWRAPPER_ACCESS_TOKEN=dw-secret\n",
        encoding="utf-8",
    )
    approve_run(result.run_dir, approved_by="tester", approved_at="2026-07-14T15:00:00+09:00", render_pdf=False)
    build_publish_dry_run(result.run_dir, env_paths=(env_path,))

    monkeypatch.setattr(DatawrapperClient, "create_and_upload", lambda self, chart: {
        "chart_id": chart["chart_id"],
        "datawrapper_id": f"dw-{chart['chart_id']}",
        "status": "ok",
        "published": True,
        "public_url": f"https://datawrapper.dwcdn.net/dw-{chart['chart_id']}/1/",
    })
    monkeypatch.setattr(datawrapper_module, "_check_datawrapper_public_url", lambda chart: {
        "chart_id": chart.get("chart_id"),
        "datawrapper_id": chart.get("datawrapper_id"),
        "url": chart.get("public_url"),
        "status": "ok",
        "http_status": 200,
        "bytes_checked": 128,
        "error": None,
    })
    monkeypatch.setattr(CpanelClient, "upload_file", lambda self, local_path, remote_dir: {"local_path": local_path, "remote_dir": remote_dir, "status": "ok", "http_status": 200})
    monkeypatch.setattr(cpanel_module, "verify_public_urls", lambda run_dir: {"schema_version": "nowhere.public_url_verification.v1", "status": "ok", "checks": []})

    first_dw = plan_datawrapper(result.run_dir, execute=True, confirm_execute="execute-ledger-test", force=True, env_paths=(env_path,))
    verify_datawrapper_urls(result.run_dir)
    second_dw = plan_datawrapper(result.run_dir, execute=True, confirm_execute="execute-ledger-test", force=True, env_paths=(env_path,))
    first_cpanel = publish_cpanel(result.run_dir, execute=True, force=True, confirm_execute="execute-ledger-test", env_paths=(env_path,))
    second_cpanel = publish_cpanel(result.run_dir, execute=True, force=True, confirm_execute="execute-ledger-test", env_paths=(env_path,))

    assert first_dw["validation"]["execute_complete"] is True
    assert (result.run_dir / "publish/datawrapper_execute_result.json").exists()
    assert second_dw["mode"] == "blocked"
    assert "Datawrapper execute already completed" in second_dw["blocked_reasons"][0]
    assert first_cpanel["validation"]["execute_complete"] is True
    assert (result.run_dir / "publish/cpanel_execute_result.json").exists()
    assert second_cpanel["mode"] == "blocked"
    assert "cPanel execute already completed" in second_cpanel["blocked_reasons"][0]

    plan_datawrapper(result.run_dir, env_paths=(env_path,))
    publish_cpanel(result.run_dir, force=True, env_paths=(env_path,))
    assert load_json(result.run_dir / "publish/datawrapper_execute_result.json")["validation"]["execute_complete"] is True
    assert load_json(result.run_dir / "publish/cpanel_execute_result.json")["validation"]["execute_complete"] is True


def test_source_audit_flags_stale_and_restricted_observations(tmp_path: Path) -> None:
    adapter_dir = tmp_path / "adapter_outputs"
    obs_dir = adapter_dir / "observations"
    obs_dir.mkdir(parents=True)
    (obs_dir / "observations.json").write_text(
        """[
          {
            "observation_id": "old-naver",
            "source_id": "src-naver",
            "field_name": "index_snapshot",
            "value": {},
            "unit": null,
            "as_of": "2026-07-13T00:00:00+00:00",
            "quality_flags": ["prototype_only", "redistribution_restricted"],
            "rights_class": "public_web_restricted"
          }
        ]
        """,
        encoding="utf-8",
    )

    report = audit_adapter_outputs(adapter_dir, stale_hours=1)

    assert report["status"] == "review_needed"
    assert report["summary"]["stale_count"] == 1
    assert report["summary"]["restricted_rights_count"] == 1
    assert report["summary"]["naver_prototype_count"] == 1
    assert report["summary"]["quality_flagged_count"] == 1
    assert any("Naver prototype snapshots" in warning for warning in report["warnings"])


def test_source_audit_summarizes_yfinance_global_price_review_flags(tmp_path: Path) -> None:
    adapter_dir = tmp_path / "adapter_outputs"
    obs_dir = adapter_dir / "observations"
    obs_dir.mkdir(parents=True)
    (obs_dir / "observations.json").write_text(
        json.dumps([
            {
                "observation_id": "yf-spy",
                "source_id": "src-yfinance",
                "field_name": "global_price_latest",
                "value": {"symbol": "SPY", "close": 505.0, "point_count": 1},
                "unit": "price",
                "as_of": "2026-07-14T00:00:00+00:00",
                "quality_flags": ["yahoo_terms_review_required", "single_point_window"],
                "rights_class": "open_source_adapter",
            }
        ]),
        encoding="utf-8",
    )

    report = audit_adapter_outputs(adapter_dir, stale_hours=999999)

    assert report["status"] == "review_needed"
    assert report["summary"]["global_price_review_count"] == 1
    assert report["global_price_review_flags"][0]["quality_flags"] == ["single_point_window", "yahoo_terms_review_required"]


def test_source_audit_summarizes_jibi_news_review_flags(tmp_path: Path) -> None:
    adapter_dir = tmp_path / "adapter_outputs"
    obs_dir = adapter_dir / "observations"
    obs_dir.mkdir(parents=True)
    (obs_dir / "observations.json").write_text(
        json.dumps([
            {
                "observation_id": "evt-review",
                "source_id": "src-jibi",
                "field_name": "news_event",
                "value": {"title": "review me"},
                "unit": None,
                "as_of": "2026-07-14T00:00:00+00:00",
                "quality_flags": ["missing_market_links", "missing_reported_claims", "unverified_news_event"],
                "rights_class": "internal_licensed",
            }
        ]),
        encoding="utf-8",
    )

    report = audit_adapter_outputs(adapter_dir, stale_hours=999999)

    assert report["status"] == "review_needed"
    assert report["summary"]["news_event_review_count"] == 1
    assert report["news_event_review_flags"][0]["quality_flags"] == ["missing_market_links", "missing_reported_claims", "unverified_news_event"]


def test_source_audit_blocks_manifest_required_field_gaps(tmp_path: Path) -> None:
    adapter_dir = tmp_path / "adapter_outputs"
    obs_dir = adapter_dir / "observations"
    obs_dir.mkdir(parents=True)
    (obs_dir / "observations.json").write_text(
        """[{"observation_id":"yf","source_id":"src-yfinance","field_name":"global_price_latest","value":{},"unit":"price","as_of":"2026-07-14T00:00:00+00:00","quality_flags":[],"rights_class":"open_source_adapter"}]""",
        encoding="utf-8",
    )
    (adapter_dir / "manifest.json").write_text(
        json.dumps({"adapter_contract": {"required_fields": ["news_event", "index_snapshot", "global_price_latest"]}}),
        encoding="utf-8",
    )

    report = audit_adapter_outputs(adapter_dir, stale_hours=999999)

    assert report["status"] == "blocked"
    assert report["summary"]["coverage"]["valid"] is False
    assert report["summary"]["coverage"]["missing_required_fields"] == ["news_event", "index_snapshot"]
    assert "missing required adapter fields" in report["blockers"][0]


def test_collect_fixture_sources_writes_adapter_contract_coverage(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    adapter_dir = collect_fixture_sources(root, "coverage-source", output_root=tmp_path)

    manifest = load_json(adapter_dir / "manifest.json")
    audit = load_json(adapter_dir / "source_audit.json")

    assert manifest["adapter_contract"]["required_fields"] == ["news_event", "index_snapshot", "global_price_latest"]
    assert audit["summary"]["coverage"]["valid"] is True
    assert audit["summary"]["coverage"]["missing_required_fields"] == []
    market = load_json(adapter_dir / "market_pack.json")
    assert audit["summary"]["news_event_review_count"] >= 1
    assert audit["summary"]["global_price_review_count"] >= 1
    assert any("news events need editorial review" in warning for warning in audit["warnings"])
    assert any("global price observations need market data review" in warning for warning in audit["warnings"])
    assert market["global_context"][0]["window_start"]
    assert market["global_context"][0]["window_end"]
    assert market["global_context"][0]["point_count"] == 2
    assert market["indices"][0]["redistribution_allowed"] is False
    assert audit["summary"]["naver_prototype_count"] >= 1


def test_preflight_includes_source_audit_summary(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    result = build_fixture_bundle(
        repo_root=root,
        fixture_dir=root / "demo/2026-07-14_1430",
        run_id="source-audit-preflight-test",
        output_root=tmp_path,
        render_pdf=False,
    )
    env_path = tmp_path / "test.env"
    env_path.write_text(
        "CPANEL_HOST=example.com\n"
        "CPANEL_USER=user\n"
        "CPANEL_TOKEN=secret-token\n"
        "CPANEL_DOCROOT=public_html/tracker\n"
        "CPANEL_DATA_DIR=public-data\n"
        "DATAWRAPPER_ACCESS_TOKEN=dw-secret\n",
        encoding="utf-8",
    )
    approve_run(result.run_dir, approved_by="tester", approved_at="2026-07-14T15:00:00+09:00", render_pdf=False)
    build_publish_dry_run(result.run_dir, env_paths=(env_path,))
    adapter_dir = result.run_dir / "adapter_outputs"
    obs_dir = adapter_dir / "observations"
    obs_dir.mkdir(parents=True)
    (obs_dir / "observations.json").write_text(
        """[{"observation_id":"yf","source_id":"src-yfinance","field_name":"global_price_latest","value":{},"unit":"price","as_of":"2026-07-13T00:00:00+00:00","quality_flags":["yahoo_terms_review_required"],"rights_class":"open_source_adapter"}]""",
        encoding="utf-8",
    )
    audit_adapter_outputs(adapter_dir, stale_hours=1)

    report = audit_run(result.run_dir, force=True, env_paths=(env_path,))

    assert report["ready"] is True
    assert "source audit review needed" in report["warnings"]
    assert report["source_audit"]["summary"]["quality_flagged_count"] == 1


def test_preflight_blocks_source_audit_coverage_gaps(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    result = build_fixture_bundle(
        repo_root=root,
        fixture_dir=root / "demo/2026-07-14_1430",
        run_id="source-audit-blocker-preflight-test",
        output_root=tmp_path,
        render_pdf=False,
    )
    env_path = tmp_path / "test.env"
    env_path.write_text(
        "CPANEL_HOST=example.com\n"
        "CPANEL_USER=user\n"
        "CPANEL_TOKEN=secret-token\n"
        "CPANEL_DOCROOT=public_html/tracker\n"
        "CPANEL_DATA_DIR=public-data\n"
        "DATAWRAPPER_ACCESS_TOKEN=dw-secret\n",
        encoding="utf-8",
    )
    approve_run(result.run_dir, approved_by="tester", approved_at="2026-07-14T15:00:00+09:00", render_pdf=False)
    build_publish_dry_run(result.run_dir, env_paths=(env_path,))
    adapter_dir = result.run_dir / "adapter_outputs"
    obs_dir = adapter_dir / "observations"
    obs_dir.mkdir(parents=True)
    (obs_dir / "observations.json").write_text(
        """[{"observation_id":"yf","source_id":"src-yfinance","field_name":"global_price_latest","value":{},"unit":"price","as_of":"2026-07-14T00:00:00+00:00","quality_flags":[],"rights_class":"open_source_adapter"}]""",
        encoding="utf-8",
    )
    (adapter_dir / "manifest.json").write_text(
        json.dumps({"adapter_contract": {"required_fields": ["news_event", "index_snapshot", "global_price_latest"]}}),
        encoding="utf-8",
    )
    audit_adapter_outputs(adapter_dir, stale_hours=999999)

    report = audit_run(result.run_dir, force=True, env_paths=(env_path,))

    assert report["ready"] is False
    assert "source audit is blocked" in report["blockers"]
    assert report["source_audit"]["summary"]["coverage"]["missing_required_fields"] == ["news_event", "index_snapshot"]


def test_build_collected_bundle_promotes_adapter_outputs(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    adapter_dir = collect_fixture_sources(root, "collected-source", output_root=tmp_path)

    result = build_collected_bundle(
        repo_root=root,
        adapter_output_dir=adapter_dir,
        run_id="collected-brief",
        output_root=tmp_path,
        render_pdf=False,
    )

    report = load_json(result.validation_report_path)
    editorial = load_json(result.run_dir / "editorial_memo.json")
    article = load_json(result.run_dir / "publish/article.json")

    assert result.run_dir.name == "collected-brief"
    assert report["status"] == "review_needed"
    assert editorial["approval"]["status"] == "draft"
    assert editorial["stories"][0]["confidence"] == "low"
    assert article["artifacts"]["lightweight_bootstrap"] == "site/chart_bootstrap.js"
    assert (result.run_dir / "adapter_outputs/source_audit.json").exists()


def test_draft_editorial_memo_is_contract_valid_for_collected_packs(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    adapter_dir = collect_fixture_sources(root, "collected-draft", output_root=tmp_path)
    market = load_json(adapter_dir / "market_pack.json")
    news = load_json(adapter_dir / "news_pack.json")

    editorial = draft_editorial_memo("collected-draft", market, news)
    schema = load_json(root / "contracts/editorial_memo.schema.json")

    assert validate_contract(editorial, schema) == []
    assert len(editorial["summary_bullets"]) == 3
    assert editorial["claim_evidence_map"][0]["evidence_ids"]


def test_approval_snapshot_blocks_mutated_inputs(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    result = build_fixture_bundle(
        repo_root=root,
        fixture_dir=root / "demo/2026-07-14_1430",
        run_id="approval-snapshot-test",
        output_root=tmp_path,
        render_pdf=False,
    )
    env_path = tmp_path / "test.env"
    env_path.write_text(
        "CPANEL_HOST=example.com\n"
        "CPANEL_USER=user\n"
        "CPANEL_TOKEN=secret-token\n"
        "CPANEL_DOCROOT=public_html/tracker\n"
        "CPANEL_DATA_DIR=public-data\n"
        "DATAWRAPPER_ACCESS_TOKEN=dw-secret\n",
        encoding="utf-8",
    )
    approve_run(result.run_dir, approved_by="tester", approved_at="2026-07-14T15:00:00+09:00", render_pdf=False)
    build_publish_dry_run(result.run_dir, env_paths=(env_path,))

    clean_snapshot = approval_snapshot_status(result.run_dir)
    clean_preflight = audit_run(result.run_dir, force=True, env_paths=(env_path,))

    assert clean_snapshot["valid"] is True
    assert clean_preflight["ready"] is True

    market_path = result.run_dir / "market_pack.json"
    market = load_json(market_path)
    market["run"].setdefault("warnings", []).append("mutated after approval")
    market_path.write_text(json.dumps(market, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    dirty_snapshot = approval_snapshot_status(result.run_dir)
    dirty_preflight = audit_run(result.run_dir, force=True, env_paths=(env_path,))
    cpanel_result = publish_cpanel(result.run_dir, execute=True, force=True, confirm_execute="approval-snapshot-test", env_paths=(env_path,))

    assert dirty_snapshot["valid"] is False
    assert "market_pack.json" in dirty_snapshot["changed_files"]
    assert dirty_preflight["ready"] is False
    assert "approval snapshot does not match current inputs" in dirty_preflight["blockers"]
    assert cpanel_result["mode"] == "blocked"
    assert "approval snapshot does not match current inputs" in cpanel_result["blocked_reasons"]


def test_cpanel_plan_includes_datawrapper_result_after_execute(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = Path(__file__).resolve().parents[1]
    result = build_fixture_bundle(
        repo_root=root,
        fixture_dir=root / "demo/2026-07-14_1430",
        run_id="dw-cpanel-asset-test",
        output_root=tmp_path,
        render_pdf=False,
    )
    env_path = tmp_path / "test.env"
    env_path.write_text(
        "CPANEL_HOST=example.com\n"
        "CPANEL_USER=user\n"
        "CPANEL_TOKEN=secret-token\n"
        "CPANEL_DOCROOT=public_html/tracker\n"
        "CPANEL_DATA_DIR=public-data\n"
        "DATAWRAPPER_ACCESS_TOKEN=dw-secret\n",
        encoding="utf-8",
    )
    approve_run(result.run_dir, approved_by="tester", approved_at="2026-07-14T15:00:00+09:00", render_pdf=False)
    build_publish_dry_run(result.run_dir, env_paths=(env_path,))
    monkeypatch.setattr(DatawrapperClient, "create_and_upload", lambda self, chart: {
        "chart_id": chart["chart_id"],
        "datawrapper_id": f"dw-{chart['chart_id']}",
        "status": "ok",
        "published": True,
        "public_url": f"https://datawrapper.dwcdn.net/dw-{chart['chart_id']}/1/",
    })

    plan_datawrapper(result.run_dir, execute=True, confirm_execute="dw-cpanel-asset-test", force=True, env_paths=(env_path,))
    cpanel_plan = publish_cpanel(result.run_dir, force=True, env_paths=(env_path,))

    assert any(item["local_path"] == "publish/data/datawrapper_result.json" for item in cpanel_plan["files"])


def test_cpanel_response_verdict_detects_uapi_errors() -> None:
    assert _cpanel_response_verdict({"status": 1, "errors": None})["ok"] is True
    assert _cpanel_response_verdict({"status": 0, "errors": ["denied"]})["ok"] is False
    assert _cpanel_response_verdict({"result": {"status": 0, "errors": ["upload failed"]}})["ok"] is False
    assert _cpanel_response_verdict("plain ok")["ok"] is True


def test_cpanel_execute_treats_api_payload_errors_as_failed_uploads(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = Path(__file__).resolve().parents[1]
    result = build_fixture_bundle(
        repo_root=root,
        fixture_dir=root / "demo/2026-07-14_1430",
        run_id="cpanel-payload-error-test",
        output_root=tmp_path,
        render_pdf=False,
    )
    env_path = tmp_path / "test.env"
    env_path.write_text(
        "CPANEL_HOST=example.com\n"
        "CPANEL_USER=user\n"
        "CPANEL_TOKEN=secret-token\n"
        "CPANEL_DOCROOT=public_html/tracker\n"
        "CPANEL_DATA_DIR=public-data\n"
        "DATAWRAPPER_ACCESS_TOKEN=dw-secret\n",
        encoding="utf-8",
    )
    approve_run(result.run_dir, approved_by="tester", approved_at="2026-07-14T15:00:00+09:00", render_pdf=False)
    build_publish_dry_run(result.run_dir, env_paths=(env_path,))

    def fake_upload(self: CpanelClient, local_path: str, remote_dir: str) -> dict[str, object]:
        verdict = _cpanel_response_verdict({"status": 0, "errors": ["api denied upload"]})
        return {"local_path": local_path, "remote_dir": remote_dir, "status": "failed", "http_status": 200, "response_verdict": verdict, "error": verdict["error"]}

    complete_datawrapper_for_cpanel(result.run_dir, env_path, "cpanel-payload-error-test", monkeypatch)
    monkeypatch.setattr(CpanelClient, "upload_file", fake_upload)
    publish_result = publish_cpanel(
        result.run_dir,
        execute=True,
        force=True,
        confirm_execute="cpanel-payload-error-test",
        env_paths=(env_path,),
    )

    assert publish_result["mode"] == "execute"
    assert publish_result["validation"]["execute_complete"] is False
    assert publish_result["validation"]["failed_upload_count"] == publish_result["validation"]["expected_upload_count"]
    assert "api denied upload" in publish_result["uploads"][0]["error"]
    assert not (result.run_dir / "publish/cpanel_execute_result.json").exists()


def test_datawrapper_execute_requires_approval_gate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = Path(__file__).resolve().parents[1]
    result = build_fixture_bundle(
        repo_root=root,
        fixture_dir=root / "demo/2026-07-14_1430",
        run_id="dw-approval-gate-test",
        output_root=tmp_path,
        render_pdf=False,
    )
    env_path = tmp_path / "test.env"
    env_path.write_text("DATAWRAPPER_ACCESS_TOKEN=secret-token\n", encoding="utf-8")
    monkeypatch.setattr(DatawrapperClient, "create_and_upload", lambda self, chart: {"chart_id": chart["chart_id"], "status": "ok", "published": True, "public_url": "https://example.test/chart"})

    draft = plan_datawrapper(result.run_dir, execute=True, confirm_execute="dw-approval-gate-test", env_paths=(env_path,))
    approve_run(result.run_dir, approved_by="tester", approved_at="2026-07-14T15:00:00+09:00", render_pdf=False)
    build_publish_dry_run(result.run_dir, env_paths=(env_path,))
    no_force = plan_datawrapper(result.run_dir, execute=True, confirm_execute="dw-approval-gate-test", env_paths=(env_path,))
    forced = plan_datawrapper(result.run_dir, execute=True, confirm_execute="dw-approval-gate-test", force=True, env_paths=(env_path,))

    assert draft["mode"] == "blocked"
    assert "approval status is not approved" in draft["blocked_reasons"]
    assert no_force["mode"] == "blocked"
    assert "public_publish_allowed is false" in no_force["blocked_reasons"][0]
    assert forced["mode"] == "execute"
    assert forced["validation"]["execute_complete"] is True
