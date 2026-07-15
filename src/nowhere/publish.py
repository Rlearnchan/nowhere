from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any

from .env import load_env, public_env_summary


@dataclass(frozen=True)
class PublishDryRunResult:
    publish_dir: Path
    manifest_path: Path
    configured: bool
    missing_keys: list[str]


def build_publish_dry_run(run_dir: Path, env_paths: tuple[Path, ...] | None = None) -> PublishDryRunResult:
    publish_dir = run_dir / 'publish'
    manifest_path = publish_dir / 'publish_manifest.json'
    values = load_env(env_paths) if env_paths is not None else load_env()
    required = ['CPANEL_HOST', 'CPANEL_USER', 'CPANEL_TOKEN', 'CPANEL_DOCROOT']
    missing = [key for key in required if not values.get(key)]

    manifest = _load_json(manifest_path)
    manifest['files'] = _publish_files_with_integrity(run_dir, manifest.get('files', []))
    manifest['publisher'] = {
        'mode': 'dry-run',
        'target': 'buykings.kr',
        'env': public_env_summary(values),
        'configured': not missing,
        'missing_keys': missing,
        'remote_plan': _remote_plan(values, manifest),
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return PublishDryRunResult(publish_dir, manifest_path, not missing, missing)


def _publish_files_with_integrity(run_dir: Path, files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for item in files:
        enriched = dict(item)
        path = run_dir / str(item.get('local_path'))
        if path.exists():
            enriched['sha256'] = _sha256(path)
            enriched['bytes'] = path.stat().st_size
        result.append(enriched)
    return result


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _remote_plan(values: dict[str, str], manifest: dict[str, Any]) -> dict[str, Any]:
    base_docroot = _nowhere_docroot(values)
    slug = manifest.get('slug', manifest.get('run_id', 'nowhere-brief'))
    public_base = (
        values.get('BUYKINGS_NOWHERE_PUBLIC_BASE_URL')
        or values.get('BUYKINGS_PUBLIC_BASE_URL')
        or values.get('CPANEL_NOWHERE_PUBLIC_BASE_URL')
        or 'https://buykings.kr'
    ).rstrip('/')
    return {
        'html': f'{base_docroot.rstrip("/")}/nowhere/{slug}/index.html' if base_docroot else None,
        'pdf': f'{base_docroot.rstrip("/")}/nowhere/{slug}/brief.pdf' if base_docroot else None,
        'data': f'{base_docroot.rstrip("/")}/nowhere/{slug}/data/' if base_docroot else None,
        'public_url': f'{public_base}/nowhere/{slug}/',
        'public_html_url': f'{public_base}/nowhere/{slug}/index.html',
        'public_pdf_url': f'{public_base}/nowhere/{slug}/brief.pdf',
        'public_data_url': f'{public_base}/nowhere/{slug}/data/',
    }


def _nowhere_docroot(values: dict[str, str]) -> str:
    explicit = values.get('CPANEL_NOWHERE_DOCROOT')
    if explicit:
        return explicit
    docroot = values.get('CPANEL_DOCROOT', '')
    normalized = docroot.rstrip('/')
    if normalized.endswith('/tracker'):
        return normalized[: -len('/tracker')]
    return normalized


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding='utf-8'))
