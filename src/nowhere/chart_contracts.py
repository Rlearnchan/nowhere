from __future__ import annotations

from pathlib import Path
from typing import Any

from .contracts import ValidationIssue, load_json, validate_contract

CHART_CONTRACT_FILES = {
    "datawrapper_specs": ("charts/datawrapper_specs.json", "datawrapper_specs.schema.json"),
    "lightweight_series": ("charts/lightweight_series.json", "lightweight_series.schema.json"),
}

_LIGHTWEIGHT_NUMERIC_FIELDS = {
    "Candlestick": ("open", "high", "low", "close"),
    "Bar": ("open", "high", "low", "close"),
    "Line": ("value",),
    "Area": ("value",),
    "Histogram": ("value",),
}


def validate_chart_payloads(payloads: dict[str, Any], contracts_dir: Path) -> dict[str, list[ValidationIssue]]:
    return {
        "datawrapper_specs": validate_datawrapper_specs(payloads.get("datawrapper"), contracts_dir),
        "lightweight_series": validate_lightweight_series(payloads.get("lightweight"), contracts_dir),
    }


def validate_chart_files(run_dir: Path, contracts_dir: Path) -> dict[str, list[ValidationIssue]]:
    issues: dict[str, list[ValidationIssue]] = {}
    for name, (local_path, _) in CHART_CONTRACT_FILES.items():
        path = run_dir / local_path
        if not path.exists():
            issues[name] = [ValidationIssue("$", f"missing chart payload {local_path}")]
            continue
        data = load_json(path)
        if name == "datawrapper_specs":
            issues[name] = validate_datawrapper_specs(data, contracts_dir)
        else:
            issues[name] = validate_lightweight_series(data, contracts_dir)
    return issues


def validate_datawrapper_specs(data: Any, contracts_dir: Path) -> list[ValidationIssue]:
    schema = load_json(contracts_dir / "datawrapper_specs.schema.json")
    issues = validate_contract(data, schema)
    if not isinstance(data, dict):
        return issues
    charts = data.get("charts", [])
    if isinstance(charts, list):
        issues.extend(_duplicate_id_issues(charts, "chart_id", "$.charts"))
        for index, chart in enumerate(charts):
            if isinstance(chart, dict):
                issues.extend(_validate_datawrapper_chart(chart, f"$.charts[{index}]"))
    return issues


def validate_lightweight_series(data: Any, contracts_dir: Path) -> list[ValidationIssue]:
    schema = load_json(contracts_dir / "lightweight_series.schema.json")
    issues = validate_contract(data, schema)
    if not isinstance(data, dict):
        return issues
    charts = data.get("charts", [])
    if isinstance(charts, list):
        issues.extend(_duplicate_id_issues(charts, "chart_id", "$.charts"))
        for chart_index, chart in enumerate(charts):
            if isinstance(chart, dict):
                issues.extend(_validate_lightweight_chart(chart, f"$.charts[{chart_index}]"))
    return issues


def flatten_chart_issues(issues: dict[str, list[ValidationIssue]]) -> dict[str, list[dict[str, str]]]:
    return {name: [issue.__dict__ for issue in values] for name, values in issues.items()}


def has_chart_issues(issues: dict[str, list[ValidationIssue]]) -> bool:
    return any(issues.values())


def _validate_datawrapper_chart(chart: dict[str, Any], path: str) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    table = chart.get("table")
    if not isinstance(table, dict):
        return issues
    columns = table.get("columns", [])
    rows = table.get("rows", [])
    if isinstance(columns, list):
        issues.extend(_duplicate_scalar_issues(columns, f"{path}.table.columns"))
    if isinstance(columns, list) and isinstance(rows, list):
        column_set = {column for column in columns if isinstance(column, str)}
        for row_index, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            missing = sorted(column_set - set(row))
            if missing:
                issues.append(ValidationIssue(f"{path}.table.rows[{row_index}]", f"row is missing table columns: {', '.join(missing)}"))
    metadata = chart.get("metadata")
    if isinstance(metadata, dict) and not metadata.get("source_ids"):
        issues.append(ValidationIssue(f"{path}.metadata.source_ids", "chart metadata must include source_ids"))
    return issues


def _validate_lightweight_chart(chart: dict[str, Any], path: str) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    series = chart.get("series", [])
    if isinstance(series, list):
        issues.extend(_duplicate_id_issues(series, "series_id", f"{path}.series"))
        for series_index, item in enumerate(series):
            if isinstance(item, dict):
                issues.extend(_validate_lightweight_series_item(item, f"{path}.series[{series_index}]"))
    return issues


def _validate_lightweight_series_item(series: dict[str, Any], path: str) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    series_type = series.get("type")
    required_numeric = _LIGHTWEIGHT_NUMERIC_FIELDS.get(str(series_type), ())
    data = series.get("data", [])
    if isinstance(data, list):
        for index, point in enumerate(data):
            if not isinstance(point, dict):
                continue
            if "time" not in point:
                issues.append(ValidationIssue(f"{path}.data[{index}]", "point is missing time"))
            for field in required_numeric:
                value = point.get(field)
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    issues.append(ValidationIssue(f"{path}.data[{index}].{field}", "expected numeric lightweight data field"))
    metadata = series.get("metadata")
    if isinstance(metadata, dict):
        for key in ("source_id", "evidence_id"):
            if not metadata.get(key):
                issues.append(ValidationIssue(f"{path}.metadata.{key}", f"series metadata must include {key}"))
    return issues


def _duplicate_id_issues(items: list[Any], key: str, path: str) -> list[ValidationIssue]:
    seen: set[str] = set()
    issues: list[ValidationIssue] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        value = item.get(key)
        if not isinstance(value, str):
            continue
        if value in seen:
            issues.append(ValidationIssue(f"{path}[{index}].{key}", f"duplicate {key}: {value}"))
        seen.add(value)
    return issues


def _duplicate_scalar_issues(items: list[Any], path: str) -> list[ValidationIssue]:
    seen: set[Any] = set()
    issues: list[ValidationIssue] = []
    for index, value in enumerate(items):
        if value in seen:
            issues.append(ValidationIssue(f"{path}[{index}]", f"duplicate value: {value}"))
        seen.add(value)
    return issues
