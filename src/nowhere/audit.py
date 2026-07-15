from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .approval import approval_snapshot_status
from .chart_contracts import flatten_chart_issues, has_chart_issues, validate_chart_files
from .cpanel import probe_cpanel, publish_cpanel
from .datawrapper import plan_datawrapper, probe_datawrapper


def audit_run(
    run_dir: Path,
    force: bool = False,
    probe_live: bool = False,
    env_paths: tuple[Path, ...] | None = None,
) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    blockers: list[str] = []
    warnings: list[str] = []

    qa_report = _read_json_if_exists(run_dir / "qa" / "validation_report.json")
    publish_manifest = _read_json_if_exists(run_dir / "publish" / "publish_manifest.json")
    adapter_validation = _read_json_if_exists(run_dir / "adapter_outputs" / "validation.json")
    source_audit = _read_json_if_exists(run_dir / "adapter_outputs" / "source_audit.json")
    contracts_dir = _contracts_dir(run_dir)
    chart_issues = validate_chart_files(run_dir, contracts_dir)

    required_files = _required_publish_files(run_dir, publish_manifest)
    for item in required_files:
        if item["required"] and not item["exists"]:
            blockers.append(f"missing required publish file: {item['local_path']}")

    approval_status = qa_report.get("approval", {}).get("status") if qa_report else None
    approval_snapshot = approval_snapshot_status(run_dir) if approval_status == "approved" else {"present": False, "valid": False}
    if approval_status != "approved":
        blockers.append("approval status is not approved")
    elif not approval_snapshot.get("valid"):
        blockers.append("approval snapshot does not match current inputs")

    if publish_manifest and not publish_manifest.get("public_publish_allowed"):
        if force:
            warnings.append("public_publish_allowed is false; force override requested")
        else:
            blockers.append("public_publish_allowed is false; pass --force to mark cPanel execution eligible")

    publisher = publish_manifest.get("publisher", {}) if publish_manifest else {}
    remote_plan = publisher.get("remote_plan", {}) if isinstance(publisher, dict) else {}
    if not remote_plan.get("public_url"):
        blockers.append("publish dry-run public URL is missing")

    cpanel_plan = publish_cpanel(run_dir, execute=False, force=force, env_paths=env_paths)
    datawrapper_plan = plan_datawrapper(run_dir, execute=False, env_paths=env_paths)
    cpanel_probe = probe_cpanel(env_paths=env_paths) if probe_live else None
    datawrapper_probe = probe_datawrapper(env_paths=env_paths) if probe_live else None

    if cpanel_plan.get("blocked"):
        blockers.extend([f"cPanel: {reason}" for reason in cpanel_plan.get("blocked_reasons", [])])
    if not cpanel_plan.get("validation", {}).get("ready_for_execute"):
        blockers.append("cPanel plan is not ready for execute")
    if not datawrapper_plan.get("validation", {}).get("ready_for_execute"):
        blockers.append("Datawrapper plan is not ready for execute")
    if has_chart_issues(chart_issues):
        blockers.append("chart payload contract validation has errors")
    if cpanel_probe and cpanel_probe.get("status") != "ok":
        blockers.append("live cPanel probe failed")
    if datawrapper_probe and datawrapper_probe.get("status") != "ok":
        blockers.append("live Datawrapper probe failed")

    adapter_summary = _adapter_summary(adapter_validation)
    source_summary = _source_audit_summary(source_audit)
    if adapter_summary["has_errors"]:
        blockers.append("adapter output validation has errors")
    if source_summary["status"] == "blocked":
        blockers.append("source audit is blocked")
    elif source_summary["status"] == "review_needed":
        warnings.append("source audit review needed")

    result = {
        "schema_version": "nowhere.preflight_report.v1",
        "run_id": publish_manifest.get("run_id") if publish_manifest else run_dir.name,
        "run_dir": str(run_dir),
        "ready": not blockers,
        "force": force,
        "probe_live": probe_live,
        "blockers": sorted(set(blockers)),
        "warnings": sorted(set(warnings)),
        "approval": {
            "status": approval_status or "missing",
            "approved_by": qa_report.get("approval", {}).get("approved_by") if qa_report else None,
            "approved_at": qa_report.get("approval", {}).get("approved_at") if qa_report else None,
            "snapshot": approval_snapshot,
        },
        "qa": {
            "status": qa_report.get("status") if qa_report else "missing",
            "public_publish_allowed": publish_manifest.get("public_publish_allowed") if publish_manifest else None,
        },
        "publish": {
            "configured": publisher.get("configured") if isinstance(publisher, dict) else None,
            "public_url": remote_plan.get("public_url"),
            "public_pdf_url": remote_plan.get("public_pdf_url"),
            "required_files": required_files,
        },
        "cpanel": {
            "configured": cpanel_plan.get("configured"),
            "blocked": cpanel_plan.get("blocked"),
            "blocked_reasons": cpanel_plan.get("blocked_reasons", []),
            "validation": cpanel_plan.get("validation", {}),
            "probe": cpanel_probe,
        },
        "datawrapper": {
            "configured": datawrapper_plan.get("configured"),
            "blocked": datawrapper_plan.get("blocked"),
            "blocked_reasons": datawrapper_plan.get("blocked_reasons", []),
            "chart_count": len(datawrapper_plan.get("charts", [])),
            "validation": datawrapper_plan.get("validation", {}),
            "probe": datawrapper_probe,
        },
        "chart_contracts": {
            "valid": not has_chart_issues(chart_issues),
            "issues": flatten_chart_issues(chart_issues),
        },
        "adapters": adapter_summary,
        "source_audit": source_summary,
        "execution_plan": _execution_plan(run_dir, publish_manifest.get("run_id") if publish_manifest else run_dir.name, force, not blockers),
    }
    output_path = run_dir / "publish" / "preflight_report.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def _contracts_dir(run_dir: Path) -> Path:
    for parent in (run_dir, *run_dir.parents):
        candidate = parent / "contracts"
        if (candidate / "datawrapper_specs.schema.json").exists() and (candidate / "lightweight_series.schema.json").exists():
            return candidate
    return Path.cwd() / "contracts"


def _execution_plan(run_dir: Path, run_id: str, force: bool, ready: bool) -> dict[str, Any]:
    force_flag = " --force" if force else ""
    run_arg = str(run_dir)
    return {
        "ready": ready,
        "confirmation": run_id,
        "commands": [
            {
                "step": "preflight",
                "write_scope": "local_report_only",
                "command": f"python -m nowhere.cli brief preflight {run_arg}{force_flag} --probe-live",
            },
            {
                "step": "datawrapper_execute",
                "write_scope": "external_datawrapper_chart_publish",
                "command": f"python -m nowhere.cli brief datawrapper-plan {run_arg} --execute --confirm-execute {run_id}{force_flag}",
            },
            {
                "step": "verify_datawrapper_urls",
                "write_scope": "read_only_datawrapper_public_url_check",
                "command": f"python -m nowhere.cli brief verify-datawrapper {run_arg}",
            },
            {
                "step": "cpanel_execute",
                "write_scope": "external_cpanel_upload_to_buykings",
                "command": f"python -m nowhere.cli brief publish-cpanel {run_arg} --execute --confirm-execute {run_id}{force_flag}",
            },
            {
                "step": "verify_public_urls",
                "write_scope": "read_only_buykings_public_url_check",
                "command": f"python -m nowhere.cli brief verify-public {run_arg}",
            },
            {
                "step": "execution_status",
                "write_scope": "local_report_only",
                "command": f"python -m nowhere.cli brief execution-status {run_arg}",
            },
        ],
    }


def _required_publish_files(run_dir: Path, publish_manifest: dict[str, Any]) -> list[dict[str, Any]]:
    files = []
    for item in publish_manifest.get("files", []) if publish_manifest else []:
        local_path = item["local_path"]
        absolute = run_dir / local_path
        files.append(
            {
                "local_path": local_path,
                "remote_role": item.get("remote_role"),
                "required": not bool(item.get("optional")),
                "exists": absolute.exists(),
                "bytes": absolute.stat().st_size if absolute.exists() else None,
            }
        )
    return files


def _adapter_summary(adapter_validation: dict[str, Any]) -> dict[str, Any]:
    if not adapter_validation:
        return {"present": False, "has_errors": False, "validation": None}
    issue_count = 0
    for value in adapter_validation.values():
        if isinstance(value, list):
            issue_count += len(value)
    return {
        "present": True,
        "has_errors": issue_count > 0,
        "issue_count": issue_count,
        "validation": adapter_validation,
    }


def _source_audit_summary(source_audit: dict[str, Any]) -> dict[str, Any]:
    if not source_audit:
        return {"present": False, "status": "missing", "warnings": [], "summary": None}
    return {
        "present": True,
        "status": source_audit.get("status", "unknown"),
        "warnings": source_audit.get("warnings", []),
        "blockers": source_audit.get("blockers", []),
        "summary": source_audit.get("summary", {}),
    }


def _read_json_if_exists(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))
