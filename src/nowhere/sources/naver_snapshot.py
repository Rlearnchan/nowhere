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
    api_base = "https://m.stock.naver.com/api/index"

    def __init__(self, fixture_path: Path | None = None, url: str | None = None, symbol: str | None = None) -> None:
        self.fixture_path = fixture_path
        self.url = url
        self.symbol = (symbol or "").upper()

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
        elif self.symbol:
            req = urlrequest.Request(
                f"{self.api_base}/{self.symbol}/basic",
                headers={"User-Agent": "nowhere-internal-snapshot/0.1"},
            )
            with urlrequest.urlopen(req, timeout=20) as response:
                payload = response.read().decode("utf-8", errors="replace")
                content_type = response.headers.get("Content-Type", "application/json")
            raw_path = None
        else:
            raise RuntimeError("Naver prototype fetch requires a fixture_path, explicit url, or symbol")
        return RawArtifact(
            source_id=request.source_id,
            captured_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            payload=payload,
            content_type=content_type,
            rights_class=self.rights_class,
            raw_path=raw_path,
            metadata={
                "adapter": self.source_name,
                "prototype_only": True,
                "redistribution_warning": True,
                "url": self.url,
                "symbol": self.symbol,
            },
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
        if self.symbol:
            return SourceHealth("naver_finance_snapshot", "review_needed", "live index prototype mode")
        return SourceHealth("naver_finance_snapshot", "review_needed", "prototype adapter requires fixture, explicit url, or symbol")




class NaverStockSnapshotAdapter:
    source_name = "naver_stock_snapshot"
    rights_class = "public_web_restricted"
    api_base = "https://m.stock.naver.com/api/stock"

    def __init__(self, ticker: str | None = None, fixture_path: Path | None = None) -> None:
        self.ticker = _normalize_ticker(ticker or "")
        self.fixture_path = fixture_path

    def fetch(self, request: SourceRequest) -> RawArtifact:
        ticker = _normalize_ticker(str(request.params.get("ticker") or self.ticker))
        if self.fixture_path:
            payload = self.fixture_path.read_text(encoding="utf-8")
            raw_path = self.fixture_path
        else:
            if not ticker:
                raise RuntimeError("Naver stock snapshot requires a ticker")
            req = urlrequest.Request(
                f"{self.api_base}/{ticker}/basic",
                headers={"User-Agent": "nowhere-internal-snapshot/0.1"},
            )
            with urlrequest.urlopen(req, timeout=20) as response:
                payload = response.read().decode("utf-8", errors="replace")
            raw_path = None
        return RawArtifact(
            source_id=request.source_id,
            captured_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            payload=payload,
            content_type="application/json",
            rights_class=self.rights_class,
            raw_path=raw_path,
            metadata={"adapter": self.source_name, "prototype_only": True, "redistribution_warning": True, "ticker": ticker},
        )

    def normalize(self, raw: RawArtifact) -> list[Observation]:
        payload = json.loads(raw.payload)
        item = _stock_snapshot_from_payload(payload, raw)
        return [
            Observation(
                observation_id=item["evidence_id"],
                source_id=raw.source_id,
                field_name="featured_stock_snapshot",
                value=item,
                unit="krw",
                as_of=item["as_of"],
                quality_flags=["prototype_only", "redistribution_restricted"],
                rights_class=raw.rights_class,
            )
        ]

    def healthcheck(self) -> SourceHealth:
        if self.fixture_path and self.fixture_path.exists():
            return SourceHealth(self.source_name, "ok", "fixture mode")
        if self.ticker:
            return SourceHealth(self.source_name, "review_needed", "live prototype mode")
        return SourceHealth(self.source_name, "review_needed", "ticker required")


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
        data = json.loads(payload)
        if isinstance(data, dict) and {"itemCode", "closePrice", "localTradedAt"}.issubset(data.keys()):
            return _index_snapshot_from_basic_payload(data)
        return data

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



def _index_snapshot_from_basic_payload(payload: dict[str, object]) -> dict[str, object]:
    symbol = str(payload.get("itemCode") or payload.get("reutersCode") or payload.get("symbolCode") or "")
    last = _number(payload.get("closePrice"))
    change = _number(payload.get("compareToPreviousClosePrice"))
    compare = payload.get("compareToPreviousPrice")
    change_code = str(compare.get("code") or "") if isinstance(compare, dict) else ""
    if change_code in {"4", "5"}:
        change = -abs(change)
    elif change_code == "2":
        change = abs(change)
    change_pct = _number(payload.get("fluctuationsRatio"))
    if change < 0:
        change_pct = -abs(change_pct)
    elif change > 0:
        change_pct = abs(change_pct)
    as_of = str(payload.get("localTradedAt") or datetime.now(timezone.utc).isoformat(timespec="seconds"))
    return {
        "evidence_id": f"naver-index-{symbol.lower()}-{as_of[:10]}",
        "symbol": symbol,
        "name": str(payload.get("stockName") or symbol),
        "last": last,
        "change": change,
        "change_pct": change_pct,
        "prev_close": round(last - change, 6),
        "open": last,
        "high": last,
        "low": last,
        "unit": "index_point",
        "as_of": as_of,
        "market_status": str(payload.get("marketStatus") or ""),
        "delay_time_name": str(payload.get("delayTimeName") or ""),
    }


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


def _stock_snapshot_from_payload(payload: dict[str, object], raw: RawArtifact) -> dict[str, object]:
    ticker = _normalize_ticker(str(payload.get("itemCode") or payload.get("reutersCode") or raw.metadata.get("ticker") or ""))
    name = str(payload.get("stockName") or ticker)
    as_of = str(payload.get("localTradedAt") or raw.captured_at)
    return {
        "evidence_id": f"naver-stock-{ticker}-{as_of[:10]}",
        "ticker": ticker,
        "name": name,
        "market": _market_from_payload(payload),
        "last": _number(payload.get("closePriceRaw") or payload.get("closePrice")),
        "change": _number(payload.get("compareToPreviousClosePriceRaw") or payload.get("compareToPreviousClosePrice")),
        "change_pct": _number(payload.get("fluctuationsRatio")),
        "volume": _int_number(payload.get("accumulatedTradingVolumeRaw") or payload.get("accumulatedTradingVolume")),
        "trading_value_krw": _int_number(payload.get("accumulatedTradingValueRaw") or payload.get("accumulatedTradingValue")),
        "market_cap_krw": _int_number(payload.get("marketValueRaw") or payload.get("marketValue")),
        "market_status": str(payload.get("marketStatus") or ""),
        "as_of": as_of,
    }


def _market_from_payload(payload: dict[str, object]) -> str:
    exchange = payload.get("stockExchangeType")
    if isinstance(exchange, dict):
        return str(exchange.get("name") or exchange.get("nameEng") or exchange.get("nameKor") or payload.get("stockExchangeName") or "")
    return str(payload.get("stockExchangeName") or "")


def _normalize_ticker(value: str) -> str:
    digits = "".join(ch for ch in value if ch.isdigit())
    return digits.zfill(6) if digits else ""


def _int_number(value: object) -> int | None:
    if value is None or value == "" or value == "N/A":
        return None
    try:
        return int(float(str(value).replace(",", "")))
    except ValueError:
        return None


def _number(value: object) -> float:
    if value is None or value == "" or value == "N/A":
        return 0.0
    return float(str(value).replace(",", ""))
