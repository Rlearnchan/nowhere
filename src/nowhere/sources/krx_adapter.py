from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any
from urllib import request as urlrequest
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from .base import Observation, RawArtifact, SourceHealth, SourceRequest


class KrxIndexAdapter:
    source_name = "krx_openapi"
    rights_class = "public_official"
    api_base = "https://data-dbg.krx.co.kr/svc/apis/idx"

    def __init__(self, fixture_path: Path | None = None, auth_key: str | None = None, market: str = "KOSPI") -> None:
        self.fixture_path = fixture_path
        self.auth_key = auth_key
        self.market = market.upper()

    def fetch(self, request: SourceRequest) -> RawArtifact:
        params = dict(request.params)
        market = str(params.get("market") or self.market).upper()
        if self.fixture_path:
            payload = self.fixture_path.read_text(encoding="utf-8")
            return RawArtifact(
                source_id=request.source_id,
                captured_at=_utc_now(),
                payload=payload,
                content_type="application/json",
                rights_class=self.rights_class,
                raw_path=self.fixture_path,
                metadata={"adapter": self.source_name, "market": market, "fixture": True},
            )
        auth_key = str(params.get("auth_key") or self.auth_key or "")
        if not auth_key:
            raise RuntimeError("KRX live fetch requires KRX_AUTH_KEY")
        requested_bas_dd = str(params.get("bas_dd") or "")
        lookback_days = int(params.get("lookback_days") or 10)
        endpoint = str(params.get("endpoint") or _endpoint_for_market(market))
        attempted: list[str] = []
        payload = ""
        content_type = "application/json"
        resolved_bas_dd = ""
        for bas_dd in _candidate_bas_dds(requested_bas_dd, lookback_days):
            attempted.append(bas_dd)
            payload, content_type = self._fetch_payload(endpoint, auth_key, bas_dd)
            try:
                rows = _rows(json.loads(payload))
            except json.JSONDecodeError:
                rows = []
            if rows:
                resolved_bas_dd = bas_dd
                break
        return RawArtifact(
            source_id=request.source_id,
            captured_at=_utc_now(),
            payload=payload,
            content_type=content_type,
            rights_class=self.rights_class,
            metadata={
                "adapter": self.source_name,
                "market": market,
                "endpoint": endpoint,
                "bas_dd": resolved_bas_dd or requested_bas_dd,
                "bas_dd_requested": requested_bas_dd,
                "bas_dd_resolved": resolved_bas_dd,
                "attempted_bas_dds": attempted,
                "lookback_days": lookback_days,
            },
        )

    def _fetch_payload(self, endpoint: str, auth_key: str, bas_dd: str) -> tuple[str, str]:
        query = urlencode({"basDd": bas_dd} if bas_dd else {})
        url = f"{self.api_base}/{endpoint}" + (f"?{query}" if query else "")
        req = urlrequest.Request(url, method="GET")
        req.add_header("AUTH_KEY", auth_key)
        req.add_header("User-Agent", "nowhere-krx-adapter/0.1")
        with urlrequest.urlopen(req, timeout=30) as response:
            payload = response.read().decode("utf-8", errors="replace")
            content_type = response.headers.get("Content-Type", "application/json")
        return payload, content_type

    def normalize(self, raw: RawArtifact) -> list[Observation]:
        payload = json.loads(raw.payload)
        rows = _rows(payload)
        observations: list[Observation] = []
        market_hint = str(raw.metadata.get("market") or "INDEX").upper()
        primary_rows = _primary_rows(rows, market_hint)
        primary_names = {str(row.get("IDX_NM") or row.get("name") or "") for row in primary_rows}
        for idx, row in enumerate(primary_rows, start=1):
            snapshot = _snapshot_from_row(row, market_hint, raw.source_id, idx)
            if snapshot["last"] == 0:
                continue
            observations.append(
                Observation(
                    observation_id=str(snapshot["evidence_id"]),
                    source_id=raw.source_id,
                    field_name="index_snapshot",
                    value=snapshot,
                    unit="index_point",
                    as_of=str(snapshot["as_of"]),
                    quality_flags=["krx_terms_review_required"],
                    rights_class=raw.rights_class,
                )
            )
        for idx, row in enumerate(_sector_rows(rows, primary_names), start=1):
            ranking = _sector_ranking_from_row(row, market_hint, raw.source_id, idx)
            if ranking["last"] == 0:
                continue
            observations.append(
                Observation(
                    observation_id=str(ranking["evidence_id"]),
                    source_id=raw.source_id,
                    field_name="sector_ranking",
                    value=ranking,
                    unit="index_point",
                    as_of=str(ranking["as_of"]),
                    quality_flags=["krx_terms_review_required"],
                    rights_class=raw.rights_class,
                )
            )
        return observations

    def healthcheck(self) -> SourceHealth:
        if self.fixture_path:
            return SourceHealth(self.source_name, "ok" if self.fixture_path.exists() else "blocked", str(self.fixture_path))
        if self.auth_key:
            return SourceHealth(self.source_name, "ok", "KRX_AUTH_KEY configured")
        return SourceHealth(self.source_name, "review_needed", "KRX_AUTH_KEY missing")


def _endpoint_for_market(market: str) -> str:
    if market.upper() == "KOSDAQ":
        return "kosdaq_dd_trd"
    return "kospi_dd_trd"


def _candidate_bas_dds(explicit_bas_dd: str, lookback_days: int) -> list[str]:
    if explicit_bas_dd:
        return [explicit_bas_dd]
    today = datetime.now(ZoneInfo("Asia/Seoul")).date()
    candidates: list[str] = []
    for offset in range(max(lookback_days, 0) + 1):
        day = today - timedelta(days=offset)
        if day.weekday() >= 5:
            continue
        candidates.append(_format_bas_dd(day))
    return candidates or [_format_bas_dd(today)]


def _format_bas_dd(value: date) -> str:
    return value.strftime("%Y%m%d")


def _rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        for key in ("OutBlock_1", "output", "data", "rows"):
            value = payload.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
        if all(key in payload for key in ("BAS_DD", "CLSPRC_IDX")):
            return [payload]
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    return []


def _primary_rows(rows: list[dict[str, Any]], market_hint: str) -> list[dict[str, Any]]:
    market = market_hint.upper()
    primary_names = {"KOSPI": {"코스피", "KOSPI"}, "KOSDAQ": {"코스닥", "KOSDAQ"}}.get(market, {market})
    exact = [row for row in rows if str(row.get("IDX_NM") or row.get("name") or "").upper() in {name.upper() for name in primary_names}]
    if exact:
        return exact[:1]
    nonzero = [row for row in rows if _number(row.get("CLSPRC_IDX") or row.get("close") or row.get("last")) != 0]
    return nonzero[:1]


def _sector_rows(rows: list[dict[str, Any]], primary_names: set[str]) -> list[dict[str, Any]]:
    primary_upper = {name.upper() for name in primary_names if name}
    result = []
    for row in rows:
        name = str(row.get("IDX_NM") or row.get("name") or "")
        if not name or name.upper() in primary_upper or "외국주포함" in name:
            continue
        if _number(row.get("CLSPRC_IDX") or row.get("close") or row.get("last")) == 0:
            continue
        result.append(row)
    return result


def _sector_ranking_from_row(row: dict[str, Any], market_hint: str, source_id: str, index: int) -> dict[str, Any]:
    snapshot = _snapshot_from_row(row, market_hint, source_id, index)
    return {
        "evidence_id": f"krx-sector-{market_hint.lower()}-{index}-{snapshot['as_of'][:10]}",
        "market": market_hint.upper(),
        "sector": str(snapshot["name"]),
        "last": snapshot["last"],
        "change": snapshot["change"],
        "change_pct": snapshot["change_pct"],
        "as_of": snapshot["as_of"],
    }


def _snapshot_from_row(row: dict[str, Any], market_hint: str, source_id: str, index: int) -> dict[str, Any]:
    symbol = str(row.get("IDX_CLSS") or row.get("MKT_NM") or row.get("market") or market_hint).upper()
    name = str(row.get("IDX_NM") or row.get("name") or symbol)
    bas_dd = str(row.get("BAS_DD") or row.get("basDd") or "")
    as_of = _as_of_from_bas_dd(bas_dd)
    last = _number(row.get("CLSPRC_IDX") or row.get("close") or row.get("last"))
    change = _number(row.get("CMPPREVDD_IDX") or row.get("change"))
    change_pct = _number(row.get("FLUC_RT") or row.get("change_pct"))
    open_value = _number(row.get("OPNPRC_IDX") or row.get("open") or last)
    high = _number(row.get("HGPRC_IDX") or row.get("high") or max(open_value, last))
    low = _number(row.get("LWPRC_IDX") or row.get("low") or min(open_value, last))
    prev_close = last - change
    evidence_id = f"krx-{symbol.lower()}-{bas_dd or index}-{index}"
    return {
        "evidence_id": evidence_id,
        "symbol": symbol,
        "name": name,
        "last": last,
        "change": change,
        "change_pct": change_pct,
        "prev_close": prev_close,
        "open": open_value,
        "high": high,
        "low": low,
        "as_of": as_of,
    }


def _number(value: Any) -> float:
    if value is None or value == "":
        return 0.0
    return float(str(value).replace(",", ""))


def _as_of_from_bas_dd(value: str) -> str:
    if len(value) == 8 and value.isdigit():
        return f"{value[:4]}-{value[4:6]}-{value[6:]}T15:30:00+09:00"
    return _utc_now()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
