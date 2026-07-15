from __future__ import annotations

from pathlib import Path
import os

DEFAULT_ENV_PATHS = (
    Path('/srv/syuka-ax/orchestrator/.env'),
    Path('.env'),
)


def load_env(paths: tuple[Path, ...] = DEFAULT_ENV_PATHS) -> dict[str, str]:
    values: dict[str, str] = {}
    for path in paths:
        if path.exists():
            values.update(_read_env_file(path))
    values.update({key: value for key, value in os.environ.items() if value is not None})
    return values


def public_env_summary(values: dict[str, str]) -> dict[str, bool]:
    keys = (
        'CPANEL_HOST',
        'CPANEL_PORT',
        'CPANEL_USER',
        'CPANEL_TOKEN',
        'CPANEL_DOCROOT',
        'CPANEL_DATA_DIR',
    )
    return {key: bool(values.get(key)) for key in keys}


def _read_env_file(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw_line in path.read_text(encoding='utf-8', errors='replace').splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        result[key.strip()] = _strip_quotes(value.strip())
    return result


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'\"', "'"}:
        return value[1:-1]
    return value
