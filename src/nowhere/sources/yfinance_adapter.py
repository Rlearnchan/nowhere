from __future__ import annotations

from datetime import datetime, timezone
import json

from .base import Observation, RawArtifact, SourceHealth, SourceRequest


class YFinanceAdapter:
    source_name = "yfinance"
    rights_class = "open_source_adapter"

    def fetch(self, request: SourceRequest) -> RawArtifact:
        try:
            import yfinance as yf
        except Exception as exc:
            raise RuntimeError("yfinance is not installed; install the market extra before live fetch") from exc

        tickers = request.params.get("tickers", [])
        period = request.params.get("period", "5d")
        interval = request.params.get("interval", "5m")
        data = yf.download(tickers, period=period, interval=interval, group_by="ticker", progress=False)
        payload = data.to_json(date_format="iso")
        return RawArtifact(
            source_id=request.source_id,
            captured_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            payload=payload,
            content_type="application/json",
            rights_class=self.rights_class,
            metadata={"adapter": self.source_name, "tickers": tickers, "period": period, "interval": interval},
        )

    def normalize(self, raw: RawArtifact) -> list[Observation]:
        payload = json.loads(raw.payload)
        observations = _normalize_yfinance_json(raw, payload)
        if observations:
            return observations
        return [
            Observation(
                observation_id=f"{raw.source_id}-raw-json",
                source_id=raw.source_id,
                field_name="yfinance_download",
                value=payload,
                unit=None,
                as_of=raw.captured_at,
                quality_flags=["raw_adapter_payload"],
                rights_class=raw.rights_class,
            )
        ]

    def healthcheck(self) -> SourceHealth:
        try:
            import yfinance  # noqa: F401
        except Exception:
            return SourceHealth("yfinance", "review_needed", "package not installed")
        return SourceHealth("yfinance", "ok")


def _normalize_yfinance_json(raw: RawArtifact, payload: object) -> list[Observation]:
    if not isinstance(payload, dict):
        return []
    observations: list[Observation] = []
    close_series = _extract_close_series(payload)
    for ticker, closes in close_series.items():
        if not closes:
            continue
        latest_time, latest_close = closes[-1]
        first_time, first_close = closes[0]
        change_pct = ((latest_close / first_close) - 1) * 100 if first_close else None
        age_hours = _age_hours(latest_time, raw.captured_at)
        stale_hours = int(raw.metadata.get("stale_hours") or 72)
        observations.append(
            Observation(
                observation_id=f"{raw.source_id}-{ticker}-latest",
                source_id=raw.source_id,
                field_name="global_price_latest",
                value={
                    "symbol": ticker,
                    "close": latest_close,
                    "change_pct_from_window_start": change_pct,
                    "window_start": first_time,
                    "window_end": latest_time,
                    "point_count": len(closes),
                    "adapter": "yfinance",
                    "period": raw.metadata.get("period"),
                    "interval": raw.metadata.get("interval"),
                    "freshness_age_hours": age_hours,
                    "stale_hours": stale_hours,
                },
                unit="price",
                as_of=latest_time or raw.captured_at,
                quality_flags=_quality_flags(first_close, len(closes), age_hours, stale_hours),
                rights_class=raw.rights_class,
            )
        )
    return observations


def _quality_flags(first_close: float, point_count: int, age_hours: float | None, stale_hours: int) -> list[str]:
    flags = ["yahoo_terms_review_required"]
    if point_count < 2:
        flags.append("single_point_window")
    if first_close == 0:
        flags.append("zero_window_start_price")
    if age_hours is None:
        flags.append("unparseable_market_timestamp")
    elif age_hours > stale_hours:
        flags.append("market_data_stale")
    return flags


def _age_hours(as_of: str | None, captured_at: str) -> float | None:
    if not as_of:
        return None
    try:
        parsed_as_of = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
        parsed_captured = datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed_as_of.tzinfo is None:
        parsed_as_of = parsed_as_of.replace(tzinfo=timezone.utc)
    if parsed_captured.tzinfo is None:
        parsed_captured = parsed_captured.replace(tzinfo=timezone.utc)
    return round(max(0.0, (parsed_captured.astimezone(timezone.utc) - parsed_as_of.astimezone(timezone.utc)).total_seconds() / 3600), 2)


def _extract_close_series(payload: dict[str, object]) -> dict[str, list[tuple[str, float]]]:
    result: dict[str, list[tuple[str, float]]] = {}
    for key, value in payload.items():
        if isinstance(value, dict) and isinstance(key, str) and key.startswith("(") and "Close" in key:
            ticker = key.split("'", 2)[1] if "'" in key else key
            result[ticker] = _series_values(value)
        elif isinstance(value, dict):
            closes = _series_values(value.get("Close") or value.get("close"))
            if closes:
                result[str(key)] = closes
    return result


def _series_values(value: object) -> list[tuple[str, float]]:
    if not isinstance(value, dict):
        return []
    result: list[tuple[str, float]] = []
    for timestamp, item in value.items():
        if item is None:
            continue
        try:
            result.append((str(timestamp), float(item)))
        except (TypeError, ValueError):
            continue
    return sorted(result, key=lambda pair: pair[0])
