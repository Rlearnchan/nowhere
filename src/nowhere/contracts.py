from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


@dataclass(frozen=True)
class ValidationIssue:
    path: str
    message: str


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_contract(data: Any, schema: dict[str, Any]) -> list[ValidationIssue]:
    validator = _SchemaValidator(schema)
    return validator.validate(data)


class _SchemaValidator:
    def __init__(self, schema: dict[str, Any]) -> None:
        self.schema = schema

    def validate(self, data: Any) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        self._validate(data, self.schema, "$", issues)
        return issues

    def _validate(
        self,
        data: Any,
        schema: dict[str, Any],
        path: str,
        issues: list[ValidationIssue],
    ) -> None:
        if "$ref" in schema:
            schema = self._resolve_ref(schema["$ref"])

        if "const" in schema and data != schema["const"]:
            issues.append(ValidationIssue(path, f"expected const {schema['const']!r}"))

        if "enum" in schema and data not in schema["enum"]:
            issues.append(ValidationIssue(path, f"expected one of {schema['enum']!r}"))

        expected_type = schema.get("type")
        if expected_type is not None and not self._matches_type(data, expected_type):
            issues.append(ValidationIssue(path, f"expected type {expected_type!r}"))
            return

        if isinstance(data, dict):
            self._validate_object(data, schema, path, issues)
        elif isinstance(data, list):
            self._validate_array(data, schema, path, issues)
        elif isinstance(data, str):
            self._validate_string(data, schema, path, issues)
        elif isinstance(data, (int, float)) and not isinstance(data, bool):
            self._validate_number(data, schema, path, issues)

    def _resolve_ref(self, ref: str) -> dict[str, Any]:
        if not ref.startswith("#/"):
            raise ValueError(f"only local schema refs are supported: {ref}")
        node: Any = self.schema
        for part in ref[2:].split("/"):
            node = node[part]
        return node

    def _validate_object(
        self,
        data: dict[str, Any],
        schema: dict[str, Any],
        path: str,
        issues: list[ValidationIssue],
    ) -> None:
        required = schema.get("required", [])
        for key in required:
            if key not in data:
                issues.append(ValidationIssue(path, f"missing required property {key!r}"))

        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            for key in data:
                if key not in properties:
                    issues.append(ValidationIssue(f"{path}.{key}", "additional property is not allowed"))

        for key, value in data.items():
            if key in properties:
                self._validate(value, properties[key], f"{path}.{key}", issues)

    def _validate_array(
        self,
        data: list[Any],
        schema: dict[str, Any],
        path: str,
        issues: list[ValidationIssue],
    ) -> None:
        min_items = schema.get("minItems")
        max_items = schema.get("maxItems")
        if min_items is not None and len(data) < min_items:
            issues.append(ValidationIssue(path, f"expected at least {min_items} items"))
        if max_items is not None and len(data) > max_items:
            issues.append(ValidationIssue(path, f"expected at most {max_items} items"))

        item_schema = schema.get("items")
        if item_schema:
            for index, value in enumerate(data):
                self._validate(value, item_schema, f"{path}[{index}]", issues)

    def _validate_string(
        self,
        data: str,
        schema: dict[str, Any],
        path: str,
        issues: list[ValidationIssue],
    ) -> None:
        min_length = schema.get("minLength")
        if min_length is not None and len(data) < min_length:
            issues.append(ValidationIssue(path, f"expected length >= {min_length}"))

        fmt = schema.get("format")
        if fmt == "date":
            try:
                date.fromisoformat(data)
            except ValueError:
                issues.append(ValidationIssue(path, "expected ISO date"))
        elif fmt == "date-time":
            try:
                datetime.fromisoformat(data.replace("Z", "+00:00"))
            except ValueError:
                issues.append(ValidationIssue(path, "expected ISO date-time"))
        elif fmt == "uri":
            parsed = urlparse(data)
            if not parsed.scheme:
                issues.append(ValidationIssue(path, "expected absolute URI"))

    def _validate_number(
        self,
        data: int | float,
        schema: dict[str, Any],
        path: str,
        issues: list[ValidationIssue],
    ) -> None:
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if minimum is not None and data < minimum:
            issues.append(ValidationIssue(path, f"expected value >= {minimum}"))
        if maximum is not None and data > maximum:
            issues.append(ValidationIssue(path, f"expected value <= {maximum}"))

    def _matches_type(self, data: Any, expected: str | list[str]) -> bool:
        if isinstance(expected, list):
            return any(self._matches_type(data, item) for item in expected)
        if expected == "object":
            return isinstance(data, dict)
        if expected == "array":
            return isinstance(data, list)
        if expected == "string":
            return isinstance(data, str)
        if expected == "number":
            return isinstance(data, (int, float)) and not isinstance(data, bool)
        if expected == "integer":
            return isinstance(data, int) and not isinstance(data, bool)
        if expected == "boolean":
            return isinstance(data, bool)
        if expected == "null":
            return data is None
        return True
