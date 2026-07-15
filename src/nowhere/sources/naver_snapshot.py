from __future__ import annotations

from datetime import datetime, timezone
from html.parser import HTMLParser
import json
from pathlib import Path
from urllib import request as urlrequest

from .base import Observation, RawArtifact, SourceHealth, SourceRequest


class NaverSnapshotAdapter:
    source_name = "naver_finance_snapshot"
    rights_class = "public_web_restricted"

    def __init__(self, fixture_path: Path | None = None, url: str | None = None) -> None:
        self.fixture_path = fixture_path
        self.url = url

    def fetch(self, request: SourceRequest) -> RawArtifact:
        if self.fixture_path:
            payload = self.fixture_path.read_text(encoding="utf-8")
            content_type = "text/html" if self.fixture_path.suffix.lower() in {".html", ".htm"} else "application/json"
            raw_path = self.fixture_path
        elif self.url:
            req = urlrequest.Request(self.url, headers={"User-Agent": "nowhere-prototype/0.1"})
            with urlrequest.urlopen(req, timeout=20) as response:
                payload = response.read().decode("utf-8", errors="replace")
                content_type = response.headers.get("Content-Type", "text/html")
            raw_path = None
        else:
            raise RuntimeError("Naver prototype fetch requires a fixture_path or explicit url")
        return RawArtifact(
            source_id=request.source_id,
            captured_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            payload=payload,
            content_type=content_type,
            rights_class=self.rights_class,
            raw_path=raw_path,
            metadata={"adapter": self.source_name, "prototype_only": True, "redistribution_warning": True, "url": self.url},
        )

    def normalize(self, raw: RawArtifact) -> list[Observation]:
        item = _load_snapshot_payload(raw.payload)
        return [
            Observation(
                observation_id=item.get("evidence_id", f"{raw.source_id}-snapshot"),
                source_id=raw.source_id,
                field_name="index_snapshot",
                value=item,
                unit=item.get("unit"),
                as_of=item.get("as_of", raw.captured_at),
                quality_flags=["prototype_only", "redistribution_restricted"],
                rights_class=raw.rights_class,
            )
        ]

    def healthcheck(self) -> SourceHealth:
        if self.fixture_path and self.fixture_path.exists():
            return SourceHealth("naver_finance_snapshot", "ok", "fixture mode")
        if self.url:
            return SourceHealth("naver_finance_snapshot", "review_needed", "live prototype mode")
        return SourceHealth("naver_finance_snapshot", "review_needed", "prototype adapter requires fixture or explicit url")


class _ScriptJsonParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._capture = False
        self.scripts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "script":
            return
        attrs_dict = {key: value for key, value in attrs}
        if attrs_dict.get("id") == "__NEXT_DATA__" or attrs_dict.get("type") == "application/json":
            self._capture = True

    def handle_data(self, data: str) -> None:
        if self._capture:
            self.scripts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self._capture = False


def _load_snapshot_payload(payload: str) -> dict[str, object]:
    stripped = payload.lstrip()
    if stripped.startswith("{"):
        return json.loads(payload)

    parser = _ScriptJsonParser()
    parser.feed(payload)
    for script in parser.scripts:
        try:
            data = json.loads(script)
        except json.JSONDecodeError:
            continue
        extracted = _find_snapshot_dict(data)
        if extracted is not None:
            return extracted
    raise ValueError("could not find Naver snapshot JSON in payload")


def _find_snapshot_dict(value: object) -> dict[str, object] | None:
    if isinstance(value, dict):
        if {"symbol", "last", "as_of"}.issubset(value.keys()):
            return value
        for child in value.values():
            found = _find_snapshot_dict(child)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_snapshot_dict(child)
            if found is not None:
                return found
    return None
