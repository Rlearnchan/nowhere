# Chart Payload Contracts

Phase 0 emits chart payloads for the existing NOWHERE toolchain instead of inventing a new renderer.

## Datawrapper Payload

File: `charts/datawrapper_specs.json`  
Schema: `contracts/datawrapper_specs.schema.json`

```json
{
  "schema_version": "nowhere.datawrapper_specs.v1",
  "charts": [
    {
      "chart_id": "market-day-range",
      "tool": "datawrapper",
      "chart_type": "d3-bars",
      "title": "KOSPI/KOSDAQ day range",
      "table": {"columns": ["market", "low", "open", "prev_close", "last", "high"], "rows": []},
      "metadata": {"source_ids": [], "evidence_ids": [], "rights_classes": []}
    }
  ]
}
```

`table` is intentionally close to the Datawrapper upload surface. The Phase 0 generator omits charts with no rows, because empty Datawrapper charts are not publish-ready. Contract validation also checks that every row contains the declared columns, chart IDs are unique, and source/evidence metadata is present.

## Lightweight Payload

File: `charts/lightweight_series.json`  
Schema: `contracts/lightweight_series.schema.json`

```json
{
  "schema_version": "nowhere.lightweight_series.v1",
  "charts": [
    {
      "chart_id": "index-range-series",
      "container_hint": "tracker",
      "series": [{"series_id": "KOSPI", "type": "Candlestick", "data": []}],
      "metadata": {"source_ids": [], "evidence_ids": []}
    }
  ]
}
```

This is designed for `lightweight-charts` on `buykings.kr`/tracker and keeps source IDs beside every chart. Contract validation checks supported series types, required numeric data fields, per-series time values, unique IDs, and source/evidence metadata.


## Published Frontend Hook

File: `publish/site/chart_bootstrap.js`

The published `index.html` includes a `#nowhere-lightweight-chart` container with `data-chart-src="../data/lightweight_series.json"`. The bootstrap script loads the payload, renders it with `lightweight-charts` when available, and falls back to latest-value text when the library or payload cannot be loaded. This keeps the tracker-facing contract explicit while preserving static PDF/HTML generation. `brief build-fixture` records chart contract results in `qa/validation_report.json`, and `brief preflight` re-validates the emitted files so damaged chart payloads block external publication.
