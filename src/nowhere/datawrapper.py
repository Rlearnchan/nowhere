from __future__ import annotations

import csv
from dataclasses import dataclass
import hashlib
from io import StringIO
import json
from pathlib import Path
import ssl
from typing import Any
from urllib import request
from urllib.error import HTTPError, URLError

from .approval import approval_snapshot_status
from .env import load_env


@dataclass(frozen=True)
class DatawrapperConfig:
    access_token: str
    api_base: str = "https://api.datawrapper.de/v3"

    @classmethod
    def from_env(cls, values: dict[str, str]) -> tuple[DatawrapperConfig | None, list[str]]:
        token = values.get("DATAWRAPPER_ACCESS_TOKEN") or values.get("DATAWRAPPER_AUTOPARK_PUBLISH_TOKEN")
        if not token:
            return None, ["DATAWRAPPER_ACCESS_TOKEN"]
        return cls(access_token=token, api_base=values.get("DATAWRAPPER_API_BASE", cls.api_base)), []


def plan_datawrapper(
    run_dir: Path,
    execute: bool = False,
    confirm_execute: str | None = None,
    force: bool = False,
    allow_reexecute: bool = False,
    env_paths: tuple[Path, ...] | None = None,
) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    specs_path = run_dir / "charts" / "datawrapper_specs.json"
    specs = _load_json(specs_path)
    manifest_path = run_dir / "publish" / "publish_manifest.json"
    manifest = _load_json(manifest_path) if manifest_path.exists() else {}
    qa_report = _load_json(run_dir / "qa" / "validation_report.json") if (run_dir / "qa" / "validation_report.json").exists() else {}
    run_id = manifest.get("run_id") or run_dir.name
    values = load_env(env_paths) if env_paths is not None else load_env()
    config, missing = DatawrapperConfig.from_env(values)
    charts = [_chart_plan(chart) for chart in specs.get("charts", [])]
    blocked_reasons: list[str] = []
    approval_status = qa_report.get("approval", {}).get("status")
    approval_snapshot = approval_snapshot_status(run_dir) if approval_status == "approved" else {"present": False, "valid": False}
    if execute and approval_status != "approved":
        blocked_reasons.append("approval status is not approved")
    elif execute and not approval_snapshot.get("valid"):
        blocked_reasons.append("approval snapshot does not match current inputs")
    elif execute and not manifest.get("public_publish_allowed") and not force:
        blocked_reasons.append("public_publish_allowed is false; pass force=True/--force to override review warnings")
    if execute and confirm_execute != run_id:
        blocked_reasons.append("execute confirmation does not match run_id")
    if execute and missing:
        blocked_reasons.append(f"missing Datawrapper env keys: {', '.join(missing)}")
    execute_result_path = run_dir / "publish" / "datawrapper_execute_result.json"
    if execute and not allow_reexecute and _existing_execute_complete(execute_result_path):
        blocked_reasons.append("Datawrapper execute already completed; pass allow_reexecute=True/--allow-reexecute to run again")
    result: dict[str, Any] = {
        "schema_version": "nowhere.datawrapper_plan.v1",
        "mode": "execute" if execute else "plan",
        "run_id": run_id,
        "configured": config is not None,
        "missing_keys": missing,
        "force": force,
        "approval_status": approval_status,
        "approval_snapshot": approval_snapshot,
        "blocked": bool(blocked_reasons),
        "blocked_reasons": blocked_reasons,
        "allow_reexecute": allow_reexecute,
        "charts": charts,
        "uploads": [],
    }
    if execute and config is not None and not blocked_reasons:
        client = DatawrapperClient(config)
        result["uploads"] = [client.create_and_upload(chart) for chart in specs.get("charts", [])]
    elif execute:
        result["mode"] = "blocked"

    result["validation"] = _validate_datawrapper_result(result)
    output_path = run_dir / "publish" / "datawrapper_plan.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(_redact_datawrapper_result(result), ensure_ascii=False, indent=2) + "\n"
    output_path.write_text(payload, encoding="utf-8")
    if result["validation"].get("execute_complete"):
        execute_result_path.write_text(payload, encoding="utf-8")
        _attach_result_to_publish_bundle(run_dir, _redact_datawrapper_result(result))
    return result


def probe_datawrapper(env_paths: tuple[Path, ...] | None = None) -> dict[str, Any]:
    values = load_env(env_paths) if env_paths is not None else load_env()
    config, missing = DatawrapperConfig.from_env(values)
    result: dict[str, Any] = {
        "schema_version": "nowhere.datawrapper_probe.v1",
        "target": "datawrapper",
        "configured": config is not None,
        "missing_keys": missing,
        "status": "missing_config" if missing else "not_run",
        "http_status": None,
        "account": None,
        "error": None,
    }
    if config is None:
        return result
    probe = DatawrapperClient(config).probe_account()
    result.update(probe)
    result["status"] = "ok" if probe.get("ok") else "failed"
    return result


def verify_datawrapper_urls(run_dir: Path) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    result_path = run_dir / "publish" / "data" / "datawrapper_result.json"
    execute_path = run_dir / "publish" / "datawrapper_execute_result.json"
    source = _load_json(result_path) if result_path.exists() else {}
    execute = _load_json(execute_path) if execute_path.exists() else {}
    charts = source.get("charts", []) if isinstance(source.get("charts"), list) else []
    checks = [_check_datawrapper_public_url(chart) for chart in charts if chart.get("public_url")]
    missing_url_count = len([chart for chart in charts if not chart.get("public_url")])
    failed = [item for item in checks if item.get("status") != "ok"]
    status = "ok" if source and charts and not failed and missing_url_count == 0 else "failed"
    result = {
        "schema_version": "nowhere.datawrapper_public_url_verification.v1",
        "run_id": source.get("run_id") or execute.get("run_id") or run_dir.name,
        "status": status,
        "source_present": bool(source),
        "expected_chart_count": len(charts),
        "checked_url_count": len(checks),
        "missing_url_count": missing_url_count,
        "failed_check_count": len(failed),
        "checks": checks,
    }
    output_path = run_dir / "publish" / "datawrapper_public_url_verification.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


class DatawrapperClient:
    def __init__(self, config: DatawrapperConfig) -> None:
        self.config = config

    def probe_account(self) -> dict[str, Any]:
        response = self._request_json("GET", "/me", b"", content_type="application/json")
        if isinstance(response, dict) and response.get("status") == "failed":
            return {"ok": False, "http_status": response.get("http_status"), "error": response.get("error")}
        account = response if isinstance(response, dict) else {}
        return {
            "ok": True,
            "http_status": account.get("http_status", 200),
            "account": {
                "id": account.get("id"),
                "email_present": bool(account.get("email")),
                "name_present": bool(account.get("name")),
            },
            "error": None,
        }

    def create_and_upload(self, chart: dict[str, Any]) -> dict[str, Any]:
        created = self._request_json(
            "POST",
            "/charts",
            json.dumps({"title": chart["title"], "type": chart.get("chart_type", "tables")}).encode("utf-8"),
            content_type="application/json",
        )
        chart_id = created.get("id") if isinstance(created, dict) else None
        if not chart_id:
            return {"chart_id": chart.get("chart_id"), "status": "failed", "error": "missing created chart id", "response": created}
        csv_payload = chart_to_csv(chart).encode("utf-8")
        upload = self._request_json("PUT", f"/charts/{chart_id}/data", csv_payload, content_type="text/csv")
        upload_ok = not (isinstance(upload, dict) and upload.get("status") == "failed")
        if not upload_ok:
            return {
                "chart_id": chart.get("chart_id"),
                "datawrapper_id": chart_id,
                "status": "failed",
                "stage": "upload_data",
                "error": upload.get("error") if isinstance(upload, dict) else None,
                "upload": upload,
            }
        publish = self._request_json("POST", f"/charts/{chart_id}/publish", b"", content_type="application/json")
        publish_ok = not (isinstance(publish, dict) and publish.get("status") == "failed")
        public_url = _public_url_from_publish(chart_id, publish)
        return {
            "chart_id": chart.get("chart_id"),
            "datawrapper_id": chart_id,
            "status": "ok" if publish_ok else "failed",
            "stage": "published" if publish_ok else "publish",
            "public_url": public_url,
            "published": publish_ok,
            "publish_version": publish.get("version") if isinstance(publish, dict) else None,
            "upload": upload,
            "publish": _redact_publish_response(publish),
        }

    def _request_json(self, method: str, path: str, body: bytes, content_type: str) -> Any:
        data = None if method == "GET" else body
        req = request.Request(f"{self.config.api_base}{path}", data=data, method=method)
        req.add_header("Authorization", f"Bearer {self.config.access_token}")
        req.add_header("Content-Type", content_type)
        try:
            with request.urlopen(req, timeout=60) as response:
                payload = response.read().decode("utf-8", errors="replace")
                return json.loads(payload) if payload.strip() else {"http_status": response.status}
        except HTTPError as exc:
            return {"status": "failed", "http_status": exc.code, "error": exc.read().decode("utf-8", errors="replace")[:1000]}
        except URLError as exc:
            return {"status": "failed", "error": str(exc.reason)}


def _check_datawrapper_public_url(chart: dict[str, Any]) -> dict[str, Any]:
    url = chart.get("public_url")
    result = {
        "chart_id": chart.get("chart_id"),
        "datawrapper_id": chart.get("datawrapper_id"),
        "url": url,
        "status": "not_run",
        "http_status": None,
        "bytes_checked": 0,
        "error": None,
    }
    if not url:
        result.update({"status": "failed", "error": "missing public_url"})
        return result
    for method in ("HEAD", "GET"):
        req = request.Request(str(url), method=method)
        req.add_header("User-Agent", "Mozilla/5.0 (compatible; NowhereBriefVerifier/0.1; +https://buykings.kr/)")
        req.add_header("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8")
        if method == "GET":
            req.add_header("Range", "bytes=0-512")
        try:
            with request.urlopen(req, timeout=20, context=ssl.create_default_context()) as response:
                sample = response.read(512) if method == "GET" else b""
                result.update({
                    "status": "ok" if 200 <= response.status < 400 else "failed",
                    "http_status": response.status,
                    "bytes_checked": len(sample),
                    "error": None,
                })
                return result
        except HTTPError as exc:
            if method == "HEAD" and exc.code in {403, 405}:
                continue
            result.update({"status": "failed", "http_status": exc.code, "error": exc.read().decode("utf-8", errors="replace")[:300]})
            return result
        except URLError as exc:
            result.update({"status": "failed", "error": str(exc.reason)})
            return result
    return result


def _attach_result_to_publish_bundle(run_dir: Path, result: dict[str, Any]) -> None:
    publish_dir = run_dir / "publish"
    data_dir = publish_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    result_path = data_dir / "datawrapper_result.json"
    payload = {
        "schema_version": "nowhere.datawrapper_result.v1",
        "run_id": result.get("run_id"),
        "generated_from": "datawrapper_execute_result.json",
        "validation": result.get("validation", {}),
        "charts": [
            {
                "chart_id": item.get("chart_id"),
                "datawrapper_id": item.get("datawrapper_id"),
                "status": item.get("status"),
                "published": item.get("published"),
                "public_url": item.get("public_url"),
                "publish_version": item.get("publish_version"),
            }
            for item in result.get("uploads", [])
        ],
    }
    result_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _update_article_datawrapper_result(publish_dir / "article.json", payload)
    _update_manifest_datawrapper_result(publish_dir / "publish_manifest.json")


def _update_article_datawrapper_result(path: Path, payload: dict[str, Any]) -> None:
    if not path.exists():
        return
    article = _load_json(path)
    article.setdefault("artifacts", {})["datawrapper_result"] = "data/datawrapper_result.json"
    article["datawrapper_public_urls"] = [chart["public_url"] for chart in payload.get("charts", []) if chart.get("public_url")]
    path.write_text(json.dumps(article, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _update_manifest_datawrapper_result(path: Path) -> None:
    if not path.exists():
        return
    manifest = _load_json(path)
    files = manifest.setdefault("files", [])
    result_file = path.parent / "data" / "datawrapper_result.json"
    entry = {
        "local_path": "publish/data/datawrapper_result.json",
        "remote_role": "chart_result",
        "optional": True,
    }
    if result_file.exists():
        entry["sha256"] = _sha256(result_file)
        entry["bytes"] = result_file.stat().st_size
    existing = next((item for item in files if item.get("local_path") == "publish/data/datawrapper_result.json"), None)
    if existing is None:
        files.append(entry)
    else:
        existing.update(entry)
    _refresh_manifest_file_integrity(path.parent.parent, manifest)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _refresh_manifest_file_integrity(run_dir: Path, manifest: dict[str, Any]) -> None:
    for item in manifest.get("files", []):
        path = run_dir / str(item.get("local_path"))
        if path.exists():
            item["sha256"] = _sha256(path)
            item["bytes"] = path.stat().st_size


def _validate_datawrapper_result(result: dict[str, Any]) -> dict[str, Any]:
    uploads = result.get("uploads", [])
    failed = [item for item in uploads if item.get("status") != "ok"]
    published = [item for item in uploads if item.get("published") is True]
    public_urls = [item.get("public_url") for item in uploads if item.get("public_url")]
    chart_count = len(result.get("charts", []))
    all_charts_processed = len(uploads) == chart_count
    all_charts_published = len(published) == chart_count
    all_public_urls_present = len(public_urls) == chart_count
    return {
        "ready_for_execute": not result.get("blocked") and result.get("configured"),
        "expected_chart_count": chart_count,
        "actual_upload_count": len(uploads),
        "failed_upload_count": len(failed),
        "published_count": len(published),
        "missing_public_url_count": chart_count - len(public_urls),
        "public_urls": public_urls,
        "execute_complete": (
            result.get("mode") == "execute"
            and all_charts_processed
            and not failed
            and all_charts_published
            and all_public_urls_present
        ),
    }


def chart_to_csv(chart: dict[str, Any]) -> str:
    table = chart.get("table", {})
    columns = table.get("columns", [])
    rows = table.get("rows", [])
    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return output.getvalue()


def _public_url_from_publish(chart_id: str, publish: Any) -> str:
    if isinstance(publish, dict):
        data = publish.get("data") if isinstance(publish.get("data"), dict) else {}
        for value in (publish.get("publicUrl"), data.get("publicUrl"), publish.get("url")):
            if isinstance(value, str) and value:
                if value.startswith("//"):
                    return f"https:{value}"
                if value.startswith("/"):
                    return f"https://www.datawrapper.de{value}"
                return value
    return f"https://www.datawrapper.de/_/{chart_id}/"


def _redact_publish_response(publish: Any) -> Any:
    if not isinstance(publish, dict):
        return publish
    return {
        "version": publish.get("version"),
        "url": publish.get("url"),
        "data": {
            "lastEditStep": (publish.get("data") or {}).get("lastEditStep") if isinstance(publish.get("data"), dict) else None,
            "publishedAt": (publish.get("data") or {}).get("publishedAt") if isinstance(publish.get("data"), dict) else None,
            "publicUrl": (publish.get("data") or {}).get("publicUrl") if isinstance(publish.get("data"), dict) else None,
        },
    }


def _chart_plan(chart: dict[str, Any]) -> dict[str, Any]:
    csv_payload = chart_to_csv(chart)
    return {
        "chart_id": chart.get("chart_id"),
        "title": chart.get("title"),
        "chart_type": chart.get("chart_type"),
        "rows": len(chart.get("table", {}).get("rows", [])),
        "columns": chart.get("table", {}).get("columns", []),
        "csv_preview": csv_payload.splitlines()[:4],
        "metadata": chart.get("metadata", {}),
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _redact_datawrapper_result(result: dict[str, Any]) -> dict[str, Any]:
    return result


def _existing_execute_complete(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        payload = _load_json(path)
    except (OSError, json.JSONDecodeError):
        return False
    return bool(payload.get("validation", {}).get("execute_complete"))


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))
