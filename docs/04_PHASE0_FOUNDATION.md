# Phase 0 Foundation Plan

## Current Repository Shape

The repository now contains two layers:

- Legacy reference-hub helpers: `src/nowhere/cli.py`, `templates/`, `schemas/`, `references/`.
- NOWHERE NOON BRIEF starter assets: `docs/`, `contracts/`, and `demo/2026-07-14_1430/`.

The missing foundation is a deterministic path from fixture inputs to publish-ready artifacts. The existing demo has a standalone PPTX generator, but the product direction is PDF plus `buykings.kr` posting, with charts delegated to Datawrapper and lightweight-charts where appropriate.

## Phase 0-2 Implementation Plan

Phase 0: foundation and fixture bundle

- Validate `market_pack.json`, `news_pack.json`, and `editorial_memo.json` against local contracts.
- Build a run directory under `runs/<run_id>/`.
- Copy fixture inputs into the run directory.
- Generate chart payloads for Datawrapper and lightweight-charts.
- Generate a print-friendly HTML brief as the PDF/source publishing surface.
- Write QA and manifest files.

Phase 1: public source adapters

- Add adapter interfaces for yfinance, OpenDART, FRED, and jibi.
- Store raw responses and normalized observations separately.
- Validate generated packs against contracts before rendering.

Phase 2: Korea intraday adapters

- Add Naver Finance snapshot adapter as `prototype_only`.
- Add KIS Open API skeleton behind explicit environment configuration.
- Preserve rights metadata and block publication if restricted data is used without approval.

## Python Version And Packages

- Python: `>=3.11`, matching the current `pyproject.toml`.
- Phase 0 uses only the Python standard library.
- Later packages to consider: `httpx`, `pydantic`, `jsonschema`, `pandas`, `yfinance`, `python-dotenv`.

## Directory Structure

```text
src/nowhere/
  contracts.py       # local contract validation
  phase0.py          # fixture bundle builder
  cli.py             # CLI entrypoint
tests/
  test_cli.py
  test_phase0.py
config/
  .gitkeep
fixtures/
  .gitkeep
runs/
  .gitkeep
```

## Source Adapter Interface

```python
class SourceAdapter(Protocol):
    source_name: str

    def fetch(self, request: SourceRequest) -> RawArtifact: ...
    def normalize(self, raw: RawArtifact) -> list[Observation]: ...
    def healthcheck(self) -> SourceHealth: ...
```

Every adapter should keep raw artifacts, captured time, source rights, timeout/retry metadata, and validation status.

## Renderer Interface

```python
class BriefRenderer(Protocol):
    def render(self, bundle: BriefBundle, output_dir: Path) -> RenderResult: ...
```

Phase 0 implements an HTML renderer. PDF generation and `buykings.kr` publication should sit behind separate renderer/publisher interfaces.

## QA Checklist

- Contract validation passes for all input packs.
- Every story and claim evidence ID resolves to a known market evidence ID or news event ID.
- Market, news, and generation timestamps are preserved separately.
- Restricted/prototype source rights are reflected in QA warnings.
- Draft or missing approval blocks public publication.
- Chart payloads are generated without live data fetches.
- HTML render includes title, summary, market structure, news, stories, watchpoints, and source/QA metadata.

## First 10 Test Cases

1. `init-day` still creates legacy reference files.
2. Fixture build creates `runs/<run_id>/manifest.json`.
3. Fixture build copies the three input packs.
4. Contract validation accepts the demo market pack.
5. Contract validation rejects a missing required field.
6. QA report flags draft editorial approval as not publishable.
7. QA evidence check passes for demo story evidence IDs.
8. Datawrapper specs include range, breadth, flow, and timeline payloads.
9. lightweight-charts payload includes index range series.
10. HTML render contains the editorial title and source metadata.
