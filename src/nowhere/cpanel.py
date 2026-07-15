from __future__ import annotations

from base64 import b64encode
from dataclasses import dataclass
import hashlib
import json
import mimetypes
from pathlib import Path
import ssl
from typing import Any
from urllib import request
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode

from .approval import approval_snapshot_status
from .chart_contracts import flatten_chart_issues, has_chart_issues, validate_chart_files
from .env import load_env, public_env_summary


@dataclass(frozen=True)
class CpanelConfig:
    host: str
    user: str
    token: str
    port: int = 2083
    docroot: str = ''
    data_dir: str = ''

    @classmethod
    def from_env(cls, values: dict[str, str]) -> tuple[CpanelConfig | None, list[str]]:
        required = ['CPANEL_HOST', 'CPANEL_USER', 'CPANEL_TOKEN', 'CPANEL_DOCROOT']
        missing = [key for key in required if not values.get(key)]
        if missing:
            return None, missing
        return (
            cls(
                host=values['CPANEL_HOST'],
                user=values['CPANEL_USER'],
                token=values['CPANEL_TOKEN'],
                port=int(values.get('CPANEL_PORT') or 2083),
                docroot=values['CPANEL_DOCROOT'],
                data_dir=values.get('CPANEL_DATA_DIR', ''),
            ),
            [],
        )


def probe_cpanel(env_paths: tuple[Path, ...] | None = None) -> dict[str, Any]:
    values = load_env(env_paths) if env_paths is not None else load_env()
    config, missing = CpanelConfig.from_env(values)
    result: dict[str, Any] = {
        'schema_version': 'nowhere.cpanel_probe.v1',
        'target': 'cpanel',
        'env': public_env_summary(values),
        'configured': config is not None,
        'missing_keys': missing,
        'status': 'missing_config' if missing else 'not_run',
        'http_status': None,
        'remote_dir_checked': config.docroot if config else None,
        'error': None,
    }
    if config is None:
        return result
    probe = CpanelClient(config).probe_directory(config.docroot)
    result.update(probe)
    result['status'] = 'ok' if probe.get('ok') else 'failed'
    return result


def publish_cpanel(
    run_dir: Path,
    execute: bool = False,
    force: bool = False,
    confirm_execute: str | None = None,
    allow_reexecute: bool = False,
    env_paths: tuple[Path, ...] | None = None,
) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    manifest_path = run_dir / 'publish' / 'publish_manifest.json'
    manifest = _load_json(manifest_path)
    qa_report = _load_json(run_dir / 'qa' / 'validation_report.json')
    values = load_env(env_paths) if env_paths is not None else load_env()
    config, missing = CpanelConfig.from_env(values)

    planned_files = _planned_files(run_dir, manifest)
    datawrapper_dependency = _datawrapper_dependency_status(run_dir)
    artifact_gate = _execution_artifact_gate(run_dir)
    blocked_reasons: list[str] = []
    approval_status = qa_report.get('approval', {}).get('status')
    approval_snapshot = approval_snapshot_status(run_dir) if approval_status == 'approved' else {'present': False, 'valid': False}
    if approval_status != 'approved':
        blocked_reasons.append('approval status is not approved')
    elif not approval_snapshot.get('valid'):
        blocked_reasons.append('approval snapshot does not match current inputs')
    elif not manifest.get('public_publish_allowed') and not force:
        blocked_reasons.append('public_publish_allowed is false; pass force=True/--force to override review warnings')
    if execute and confirm_execute != manifest.get('run_id'):
        blocked_reasons.append('execute confirmation does not match run_id')
    execute_result_path = run_dir / 'publish' / 'cpanel_execute_result.json'
    if execute and not allow_reexecute and _existing_execute_complete(execute_result_path):
        blocked_reasons.append('cPanel execute already completed; pass allow_reexecute=True/--allow-reexecute to run again')
    if execute and datawrapper_dependency.get('required') and not datawrapper_dependency.get('ready_for_cpanel'):
        blocked_reasons.append('Datawrapper execute and URL verification must complete before cPanel execute')
    if execute:
        blocked_reasons.extend(artifact_gate['blocked_reasons'])
    if missing:
        blocked_reasons.append(f'missing cPanel env keys: {", ".join(missing)}')
    if any(item.get('missing') and not item.get('optional') for item in planned_files):
        blocked_reasons.append('one or more required publish files are missing')
    if execute and any(item.get('hash_mismatch') for item in planned_files):
        blocked_reasons.append('one or more publish file hashes do not match manifest')

    result: dict[str, Any] = {
        'schema_version': 'nowhere.cpanel_publish_result.v1',
        'mode': 'execute' if execute else 'plan',
        'target': 'buykings.kr',
        'run_id': manifest.get('run_id'),
        'slug': manifest.get('slug'),
        'env': public_env_summary(values),
        'configured': config is not None,
        'blocked': bool(blocked_reasons),
        'approval_status': approval_status,
        'approval_snapshot': approval_snapshot,
        'blocked_reasons': blocked_reasons,
        'allow_reexecute': allow_reexecute,
        'datawrapper_dependency': datawrapper_dependency,
        'artifact_gate': artifact_gate,
        'files': planned_files,
        'uploads': [],
    }

    if execute and not blocked_reasons and config is not None:
        client = CpanelClient(config)
        result['uploads'] = [client.upload_file(item['absolute_path'], item['remote_dir']) for item in planned_files if not item.get('missing')]
    elif execute and blocked_reasons:
        result['mode'] = 'blocked'

    result['validation'] = _validate_publish_result(result)
    if result['validation'].get('execute_complete'):
        result['public_url_verification'] = verify_public_urls(run_dir)
        _apply_public_verification_to_validation(result)
    payload = json.dumps(_without_absolute_paths(result), ensure_ascii=False, indent=2) + '\n'
    output_path = run_dir / 'publish' / 'cpanel_publish_result.json'
    output_path.write_text(payload, encoding='utf-8')
    if result['validation'].get('execute_complete'):
        execute_result_path.write_text(payload, encoding='utf-8')
    return result


def _execution_artifact_gate(run_dir: Path) -> dict[str, Any]:
    chart_issues = validate_chart_files(run_dir, _contracts_dir(run_dir))
    adapter_validation = _load_json_if_exists(run_dir / 'adapter_outputs' / 'validation.json')
    source_audit = _load_json_if_exists(run_dir / 'adapter_outputs' / 'source_audit.json')
    blocked_reasons: list[str] = []
    if has_chart_issues(chart_issues):
        blocked_reasons.append('chart payload contract validation has errors')
    if _adapter_validation_has_errors(adapter_validation):
        blocked_reasons.append('adapter output validation has errors')
    if source_audit.get('status') == 'blocked':
        blocked_reasons.append('source audit is blocked')
    return {
        'ready_for_execute': not blocked_reasons,
        'blocked_reasons': blocked_reasons,
        'chart_contracts': {
            'valid': not has_chart_issues(chart_issues),
            'issues': flatten_chart_issues(chart_issues),
        },
        'adapter_validation': {
            'present': bool(adapter_validation),
            'has_errors': _adapter_validation_has_errors(adapter_validation),
        },
        'source_audit': {
            'present': bool(source_audit),
            'status': source_audit.get('status') if source_audit else 'missing',
        },
    }


def _contracts_dir(run_dir: Path) -> Path:
    for parent in (run_dir, *run_dir.parents):
        candidate = parent / 'contracts'
        if (candidate / 'datawrapper_specs.schema.json').exists() and (candidate / 'lightweight_series.schema.json').exists():
            return candidate
    return Path.cwd() / 'contracts'


def _adapter_validation_has_errors(validation: dict[str, Any]) -> bool:
    for value in validation.values():
        if isinstance(value, list) and value:
            return True
    return False


def _datawrapper_dependency_status(run_dir: Path) -> dict[str, Any]:
    specs = _load_json_if_exists(run_dir / 'charts' / 'datawrapper_specs.json')
    chart_count = len(specs.get('charts', [])) if isinstance(specs.get('charts'), list) else 0
    required = chart_count > 0
    execute = _load_json_if_exists(run_dir / 'publish' / 'datawrapper_execute_result.json')
    verification_path = run_dir / 'publish' / 'datawrapper_public_url_verification.json'
    verification = _load_json_if_exists(verification_path)
    execute_complete = bool(execute.get('validation', {}).get('execute_complete'))
    verification_ok = verification.get('status') == 'ok'
    ready = (not required) or (execute_complete and verification_ok)
    return {
        'required': required,
        'chart_count': chart_count,
        'execute_result_present': bool(execute),
        'execute_complete': execute_complete,
        'verification_present': bool(verification),
        'verification_status': verification.get('status') if verification else 'missing',
        'ready_for_cpanel': ready,
    }


def _apply_public_verification_to_validation(result: dict[str, Any]) -> None:
    verification = result.get('public_url_verification') if isinstance(result.get('public_url_verification'), dict) else {}
    status = verification.get('status')
    result['validation']['public_url_verification_status'] = status or 'missing'
    result['validation']['public_url_verified'] = status == 'ok'
    if status != 'ok':
        result['validation']['execute_complete'] = False
        result.setdefault('post_upload_blockers', []).append('public URL verification failed after cPanel upload')


def _validate_publish_result(result: dict[str, Any]) -> dict[str, Any]:
    required_files = [item for item in result.get('files', []) if not item.get('optional')]
    missing_required = [item['local_path'] for item in required_files if item.get('missing')]
    uploads = result.get('uploads', [])
    failed_uploads = [item for item in uploads if item.get('status') != 'ok']
    expected_upload_count = len([item for item in result.get('files', []) if not item.get('missing')])
    return {
        'ready_for_execute': not result.get('blocked') and not missing_required,
        'missing_required_files': missing_required,
        'expected_upload_count': expected_upload_count,
        'actual_upload_count': len(uploads),
        'failed_upload_count': len(failed_uploads),
        'public_url_verification_status': 'not_run',
        'public_url_verified': False,
        'execute_complete': result.get('mode') == 'execute' and len(uploads) == expected_upload_count and not failed_uploads,
    }


class CpanelClient:
    def __init__(self, config: CpanelConfig) -> None:
        self.config = config

    def probe_directory(self, remote_dir: str) -> dict[str, Any]:
        params = urlencode({'dir': remote_dir})
        endpoint = f'https://{self.config.host}:{self.config.port}/execute/Fileman/list_files?{params}'
        req = request.Request(endpoint, method='GET')
        req.add_header('Authorization', f'cpanel {self.config.user}:{self.config.token}')
        try:
            with request.urlopen(req, timeout=30, context=ssl.create_default_context()) as response:
                payload = response.read().decode('utf-8', errors='replace')
                parsed = _safe_json(payload)
                return {
                    'ok': True,
                    'http_status': response.status,
                    'remote_dir_checked': remote_dir,
                    'response_shape': _response_shape(parsed),
                    'error': None,
                }
        except HTTPError as exc:
            return {'ok': False, 'http_status': exc.code, 'remote_dir_checked': remote_dir, 'error': exc.read().decode('utf-8', errors='replace')[:1000]}
        except URLError as exc:
            return {'ok': False, 'remote_dir_checked': remote_dir, 'error': str(exc.reason)}

    def upload_file(self, local_path: str, remote_dir: str) -> dict[str, Any]:
        path = Path(local_path)
        boundary = '----nowhere-cpanel-boundary'
        body = _multipart_body(boundary, {'dir': remote_dir, 'overwrite': '1'}, path)
        endpoint = f'https://{self.config.host}:{self.config.port}/execute/Fileman/upload_files'
        req = request.Request(endpoint, data=body, method='POST')
        req.add_header('Authorization', f'cpanel {self.config.user}:{self.config.token}')
        req.add_header('Content-Type', f'multipart/form-data; boundary={boundary}')
        req.add_header('Content-Length', str(len(body)))
        try:
            with request.urlopen(req, timeout=60, context=ssl.create_default_context()) as response:
                payload = response.read().decode('utf-8', errors='replace')
                parsed = _safe_json(payload)
                verdict = _cpanel_response_verdict(parsed)
                return {
                    'local_path': str(path),
                    'remote_dir': remote_dir,
                    'status': 'ok' if verdict['ok'] else 'failed',
                    'http_status': response.status,
                    'response': parsed,
                    'response_verdict': verdict,
                    'error': verdict.get('error'),
                }
        except HTTPError as exc:
            return {'local_path': str(path), 'remote_dir': remote_dir, 'status': 'failed', 'http_status': exc.code, 'error': exc.read().decode('utf-8', errors='replace')}
        except URLError as exc:
            return {'local_path': str(path), 'remote_dir': remote_dir, 'status': 'failed', 'error': str(exc.reason)}


def verify_public_urls(run_dir: Path) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    manifest = _load_json(run_dir / 'publish' / 'publish_manifest.json')
    values = load_env()
    remote_plan = manifest.get('publisher', {}).get('remote_plan', {})
    public_url = str(remote_plan.get('public_url') or '').rstrip('/')
    public_data_url = str(remote_plan.get('public_data_url') or f'{public_url}/data').rstrip('/') if public_url else ''
    urls = [
        {'role': 'html', 'url': remote_plan.get('public_html_url') or remote_plan.get('public_url')},
        {'role': 'pdf', 'url': remote_plan.get('public_pdf_url'), 'optional': True},
        {'role': 'asset', 'url': f'{public_url}/chart_bootstrap.js' if public_url else None},
        {'role': 'lightweight_series', 'url': f'{public_data_url}/lightweight_series.json' if public_data_url else None},
        {'role': 'datawrapper_result', 'url': f'{public_data_url}/datawrapper_result.json' if public_data_url else None, 'optional': True},
    ]
    auth_header = _basic_auth_header(values)
    checks = [_check_public_url(item, auth_header=auth_header) for item in urls if item.get('url')]
    required_failures = [item for item in checks if not item.get('optional') and item.get('status') != 'ok']
    result = {
        'schema_version': 'nowhere.public_url_verification.v1',
        'run_id': manifest.get('run_id'),
        'slug': manifest.get('slug'),
        'status': 'ok' if not required_failures else 'failed',
        'auth_configured': bool(auth_header),
        'checks': checks,
    }
    output_path = run_dir / 'publish' / 'public_url_verification.json'
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return result


def _check_public_url(item: dict[str, Any], auth_header: str | None = None) -> dict[str, Any]:
    url = item.get('url')
    result = {'role': item.get('role'), 'url': url, 'optional': bool(item.get('optional')), 'status': 'not_run', 'http_status': None, 'bytes_checked': 0, 'error': None}
    for method in ('HEAD', 'GET'):
        req = request.Request(str(url), method=method)
        req.add_header('User-Agent', 'Mozilla/5.0 (compatible; NowhereBriefVerifier/0.1; +https://buykings.kr/)')
        req.add_header('Accept', 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8')
        if auth_header:
            req.add_header('Authorization', auth_header)
        if method == 'GET':
            req.add_header('Range', 'bytes=0-512')
        try:
            with request.urlopen(req, timeout=20, context=ssl.create_default_context()) as response:
                sample = response.read(512) if method == 'GET' else b''
                result.update({'status': 'ok' if 200 <= response.status < 400 else 'failed', 'http_status': response.status, 'bytes_checked': len(sample), 'error': None})
                return result
        except HTTPError as exc:
            if method == 'HEAD' and exc.code in {403, 405}:
                continue
            result.update({'status': 'failed', 'http_status': exc.code, 'error': exc.read().decode('utf-8', errors='replace')[:300]})
            return result
        except URLError as exc:
            result.update({'status': 'failed', 'error': str(exc.reason)})
            return result
    return result


def _planned_files(run_dir: Path, manifest: dict[str, Any]) -> list[dict[str, Any]]:
    slug = manifest.get('slug', manifest.get('run_id', 'nowhere-brief'))
    files = []
    for item in manifest.get('files', []):
        local_path = run_dir / item['local_path']
        remote_dir = _remote_dir_for_role(manifest, item['remote_role'], slug)
        exists = local_path.exists()
        actual_sha = _sha256(local_path) if exists else None
        expected_sha = item.get('sha256')
        files.append({
            'local_path': item['local_path'],
            'absolute_path': str(local_path),
            'remote_role': item['remote_role'],
            'remote_dir': remote_dir,
            'optional': bool(item.get('optional')),
            'missing': not exists,
            'bytes': local_path.stat().st_size if exists else None,
            'expected_bytes': item.get('bytes'),
            'sha256': actual_sha,
            'expected_sha256': expected_sha,
            'hash_mismatch': bool(exists and expected_sha and actual_sha != expected_sha),
        })
    return files


def _remote_dir_for_role(manifest: dict[str, Any], role: str, slug: str) -> str:
    publisher = manifest.get('publisher', {})
    remote_plan = publisher.get('remote_plan', {})
    html_dir = str(Path(remote_plan['html']).parent) if remote_plan.get('html') else f'public_html/tracker/nowhere/{slug}'
    if role in {'article_html', 'article_pdf', 'article_asset'}:
        return html_dir
    if role in {'article_data', 'chart_specs', 'chart_series', 'chart_result', 'qa'}:
        return str(Path(html_dir) / 'data')
    return html_dir


def _basic_auth_header(values: dict[str, str]) -> str | None:
    user = values.get('BUYKINGS_BASIC_AUTH_USER') or values.get('CPANEL_PUBLIC_BASIC_AUTH_USER')
    password = values.get('BUYKINGS_BASIC_AUTH_PASSWORD') or values.get('CPANEL_PUBLIC_BASIC_AUTH_PASSWORD')
    if not user or not password:
        return None
    token = b64encode(f'{user}:{password}'.encode('utf-8')).decode('ascii')
    return f'Basic {token}'


def _multipart_body(boundary: str, fields: dict[str, str], file_path: Path) -> bytes:
    chunks: list[bytes] = []
    for key, value in fields.items():
        chunks.append(f'--{boundary}\r\n'.encode())
        chunks.append(f'Content-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode())
    mime = mimetypes.guess_type(file_path.name)[0] or 'application/octet-stream'
    chunks.append(f'--{boundary}\r\n'.encode())
    chunks.append(f'Content-Disposition: form-data; name="file-1"; filename="{file_path.name}"\r\n'.encode())
    chunks.append(f'Content-Type: {mime}\r\n\r\n'.encode())
    chunks.append(file_path.read_bytes())
    chunks.append(b'\r\n')
    chunks.append(f'--{boundary}--\r\n'.encode())
    return b''.join(chunks)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _without_absolute_paths(result: dict[str, Any]) -> dict[str, Any]:
    cleaned = dict(result)
    cleaned['files'] = [
        {key: value for key, value in item.items() if key != 'absolute_path'}
        for item in result.get('files', [])
    ]
    cleaned['uploads'] = [
        {key: value for key, value in item.items() if key != 'local_path'}
        for item in result.get('uploads', [])
    ]
    return cleaned


def _cpanel_response_verdict(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {'ok': True, 'error': None, 'reason': 'non_json_response'}

    errors = payload.get('errors')
    if errors:
        return {'ok': False, 'error': _format_cpanel_error(errors), 'reason': 'errors'}

    status = payload.get('status')
    if status in {0, '0', False}:
        return {'ok': False, 'error': _format_cpanel_error(payload.get('messages') or payload), 'reason': 'status_false'}

    result = payload.get('result')
    if isinstance(result, dict):
        result_errors = result.get('errors')
        if result_errors:
            return {'ok': False, 'error': _format_cpanel_error(result_errors), 'reason': 'result_errors'}
        result_status = result.get('status')
        if result_status in {0, '0', False}:
            return {'ok': False, 'error': _format_cpanel_error(result.get('messages') or result), 'reason': 'result_status_false'}

    return {'ok': True, 'error': None, 'reason': 'ok'}


def _format_cpanel_error(value: Any) -> str:
    if value is None:
        return 'cPanel API reported failure'
    if isinstance(value, str):
        return value[:1000]
    if isinstance(value, list):
        return '; '.join(str(item) for item in value)[:1000]
    return json.dumps(value, ensure_ascii=False)[:1000]


def _response_shape(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict):
        return {
            'type': 'object',
            'keys': sorted(str(key) for key in payload.keys())[:20],
            'has_errors': bool(payload.get('errors')),
        }
    if isinstance(payload, list):
        return {'type': 'array', 'length': len(payload)}
    return {'type': type(payload).__name__}


def _safe_json(payload: str) -> Any:
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return payload[:1000]


def _existing_execute_complete(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        payload = _load_json(path)
    except (OSError, json.JSONDecodeError):
        return False
    return bool(payload.get('validation', {}).get('execute_complete'))


def _load_json_if_exists(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return _load_json(path)
    except (OSError, json.JSONDecodeError):
        return {}


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding='utf-8'))
