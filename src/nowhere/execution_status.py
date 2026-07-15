from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .approval import approval_snapshot_status


def summarize_execution_status(run_dir: Path) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    qa_report = _read_json(run_dir / "qa" / "validation_report.json")
    manifest = _read_json(run_dir / "publish" / "publish_manifest.json")
    preflight = _read_json(run_dir / "publish" / "preflight_report.json")
    datawrapper_plan = _read_json(run_dir / "publish" / "datawrapper_plan.json")
    datawrapper_execute = _read_json(run_dir / "publish" / "datawrapper_execute_result.json")
    datawrapper_verify = _read_json(run_dir / "publish" / "datawrapper_public_url_verification.json")
    cpanel_publish = _read_json(run_dir / "publish" / "cpanel_publish_result.json")
    cpanel_execute = _read_json(run_dir / "publish" / "cpanel_execute_result.json")
    buykings_verify = _read_json(run_dir / "publish" / "public_url_verification.json")

    approval_status = qa_report.get("approval", {}).get("status", "missing") if qa_report else "missing"
    snapshot = approval_snapshot_status(run_dir) if approval_status == "approved" else {"present": False, "valid": False}
    dw_complete = bool(datawrapper_execute.get("validation", {}).get("execute_complete"))
    cpanel_complete = bool(cpanel_execute.get("validation", {}).get("execute_complete"))
    dw_verified = datawrapper_verify.get("status") == "ok"
    buykings_verified = buykings_verify.get("status") == "ok"
    external_writes_started = bool(_is_execute_attempt(datawrapper_plan) or datawrapper_execute or _is_execute_attempt(cpanel_publish) or cpanel_execute)
    complete = bool(dw_complete and cpanel_complete and dw_verified and buykings_verified)

    result = {
        "schema_version": "nowhere.execution_status.v1",
        "run_id": manifest.get("run_id") or run_dir.name,
        "run_dir": str(run_dir),
        "complete": complete,
        "external_writes_started": external_writes_started,
        "approval": {
            "status": approval_status,
            "snapshot_valid": bool(snapshot.get("valid")),
            "snapshot_present": bool(snapshot.get("present")),
        },
        "preflight": {
            "present": bool(preflight),
            "ready": preflight.get("ready") if preflight else None,
            "blocker_count": len(preflight.get("blockers", [])) if preflight else None,
            "warning_count": len(preflight.get("warnings", [])) if preflight else None,
        },
        "datawrapper": {
            "latest_mode": datawrapper_plan.get("mode") if datawrapper_plan else "missing",
            "latest_blocked": bool(datawrapper_plan.get("blocked")) if datawrapper_plan else None,
            "latest_blocked_reasons": datawrapper_plan.get("blocked_reasons", []) if datawrapper_plan else [],
            "latest_execute_complete": bool(datawrapper_plan.get("validation", {}).get("execute_complete")) if datawrapper_plan else False,
            "execute_result_present": bool(datawrapper_execute),
            "execute_complete": dw_complete,
            "published_count": datawrapper_execute.get("validation", {}).get("published_count"),
            "public_url_count": len(datawrapper_execute.get("validation", {}).get("public_urls", [])) if datawrapper_execute else 0,
            "public_urls_verified": dw_verified,
            "verification_status": datawrapper_verify.get("status") if datawrapper_verify else "missing",
        },
        "cpanel": {
            "latest_mode": cpanel_publish.get("mode") if cpanel_publish else "missing",
            "latest_blocked": bool(cpanel_publish.get("blocked")) if cpanel_publish else None,
            "latest_blocked_reasons": cpanel_publish.get("blocked_reasons", []) if cpanel_publish else [],
            "latest_post_upload_blockers": cpanel_publish.get("post_upload_blockers", []) if cpanel_publish else [],
            "latest_execute_complete": bool(cpanel_publish.get("validation", {}).get("execute_complete")) if cpanel_publish else False,
            "execute_result_present": bool(cpanel_execute),
            "execute_complete": cpanel_complete,
            "uploaded_count": (cpanel_execute or cpanel_publish).get("validation", {}).get("actual_upload_count") if (cpanel_execute or cpanel_publish) else None,
            "public_urls_verified": buykings_verified,
            "verification_status": buykings_verify.get("status") if buykings_verify else "missing",
        },
        "artifacts": {
            "preflight_report": _artifact(run_dir, "publish/preflight_report.json"),
            "datawrapper_plan": _artifact(run_dir, "publish/datawrapper_plan.json"),
            "datawrapper_execute_result": _artifact(run_dir, "publish/datawrapper_execute_result.json"),
            "datawrapper_public_url_verification": _artifact(run_dir, "publish/datawrapper_public_url_verification.json"),
            "cpanel_publish_result": _artifact(run_dir, "publish/cpanel_publish_result.json"),
            "cpanel_execute_result": _artifact(run_dir, "publish/cpanel_execute_result.json"),
            "public_url_verification": _artifact(run_dir, "publish/public_url_verification.json"),
        },
    }
    output_path = run_dir / "publish" / "execution_status.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def _is_execute_attempt(payload: dict[str, Any]) -> bool:
    return payload.get("mode") == "execute"


def _artifact(run_dir: Path, local_path: str) -> dict[str, Any]:
    path = run_dir / local_path
    return {
        "local_path": local_path,
        "exists": path.exists(),
        "bytes": path.stat().st_size if path.exists() else None,
    }


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"_invalid_json": True}
