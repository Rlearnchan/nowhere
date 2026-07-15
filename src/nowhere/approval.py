from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from .contracts import load_json
from .phase0 import PACK_FILES, build_fixture_bundle


def approve_run(
    run_dir: Path,
    approved_by: str,
    approved_at: str | None = None,
    notes: str | None = None,
    render_pdf: bool = True,
) -> Path:
    run_dir = run_dir.resolve()
    memo_path = run_dir / PACK_FILES["editorial_memo"]
    memo = load_json(memo_path)
    approval = memo.setdefault("approval", {})
    approval["status"] = "approved"
    approval["approved_by"] = approved_by
    approval["approved_at"] = approved_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    if notes is not None:
        approval["notes"] = notes
    memo_path.write_text(json.dumps(memo, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    validation_path = _rebuild_from_run_inputs(run_dir, render_pdf=render_pdf)
    _write_approval_snapshot(run_dir)
    return validation_path


def reject_run(
    run_dir: Path,
    rejected_by: str,
    notes: str,
    rejected_at: str | None = None,
    render_pdf: bool = False,
) -> Path:
    run_dir = run_dir.resolve()
    memo_path = run_dir / PACK_FILES["editorial_memo"]
    memo = load_json(memo_path)
    approval = memo.setdefault("approval", {})
    approval["status"] = "rejected"
    approval["approved_by"] = rejected_by
    approval["approved_at"] = rejected_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    approval["notes"] = notes
    memo_path.write_text(json.dumps(memo, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return _rebuild_from_run_inputs(run_dir, render_pdf=render_pdf)


def approval_status(run_dir: Path) -> dict[str, Any]:
    memo = load_json(run_dir / PACK_FILES["editorial_memo"])
    return memo.get("approval", {"status": "draft"})


def approval_snapshot_status(run_dir: Path) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    snapshot_path = run_dir / "qa" / "approval_snapshot.json"
    if not snapshot_path.exists():
        return {"present": False, "valid": False, "changed_files": [], "missing_files": [], "reason": "approval snapshot is missing"}
    snapshot = load_json(snapshot_path)
    changed: list[str] = []
    missing: list[str] = []
    expected = snapshot.get("input_hashes", {})
    for filename, sha in expected.items():
        path = run_dir / filename
        if not path.exists():
            missing.append(filename)
        elif _sha256(path) != sha:
            changed.append(filename)
    return {
        "present": True,
        "valid": not changed and not missing,
        "approved_at": snapshot.get("approved_at"),
        "approved_by": snapshot.get("approved_by"),
        "changed_files": changed,
        "missing_files": missing,
        "snapshot_path": str(snapshot_path),
    }


def _write_approval_snapshot(run_dir: Path) -> Path:
    approval = approval_status(run_dir)
    payload = {
        "schema_version": "nowhere.approval_snapshot.v1",
        "run_id": run_dir.name,
        "approved_by": approval.get("approved_by"),
        "approved_at": approval.get("approved_at"),
        "input_hashes": {filename: _sha256(run_dir / filename) for filename in PACK_FILES.values()},
    }
    path = run_dir / "qa" / "approval_snapshot.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _find_repo_root(path: Path) -> Path:
    for candidate in (path, *path.parents, Path.cwd()):
        if (candidate / "contracts").is_dir() and (candidate / "pyproject.toml").exists():
            return candidate
    # For runs/<run_id>, the repository root is usually two levels up.
    return path.parents[1]


def _rebuild_from_run_inputs(run_dir: Path, render_pdf: bool) -> Path:
    with TemporaryDirectory() as tmpdir:
        fixture_dir = Path(tmpdir) / "fixture"
        fixture_dir.mkdir()
        for filename in PACK_FILES.values():
            shutil.copy2(run_dir / filename, fixture_dir / filename)
        result = build_fixture_bundle(
            repo_root=_find_repo_root(run_dir),
            fixture_dir=fixture_dir,
            run_id=run_dir.name,
            output_root=run_dir.parent,
            render_pdf=render_pdf,
        )
    return result.validation_report_path
