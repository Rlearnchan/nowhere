# NOWHERE NOON BRIEF - Codex Starter Pack

한국 장중 시황 라이브를 위한 3-5페이지 보조자료 제작 프로젝트의 시작점입니다.

이 저장소의 기본 가정은 단순합니다.

- **Codex**는 데이터를 모으고, 정규화하고, 계산하고, 차트를 만들고, 결과물을 렌더링합니다.
- **GPT 전문가 단계**는 어떤 이슈가 중요한지 판단하고, 시장 반응과 뉴스를 연결하고, 반론과 확인 조건을 만듭니다.
- **사람**은 최종 논지와 공개 문구를 승인합니다.
- 자동화의 목표는 판단을 없애는 것이 아니라, **좋은 판단이 반복 가능하도록 전후 공정을 고정하는 것**입니다.

## 먼저 읽을 문서

1. [`docs/00_CODEX_THREAD_PROMPT.md`](docs/00_CODEX_THREAD_PROMPT.md) - 새 Codex 스레드에 붙여 넣을 시작 프롬프트
2. [`docs/01_PRODUCT_STARTER.md`](docs/01_PRODUCT_STARTER.md) - 제품 철학, 범위, 아키텍처, 구현 백로그
3. [`docs/02_DATA_SOURCES_AND_ACQUISITION.md`](docs/02_DATA_SOURCES_AND_ACQUISITION.md) - 필요한 데이터, 추천 소스, 조달 방식, 한계
4. [`docs/03_DEMO_FORMAT_SPEC.md`](docs/03_DEMO_FORMAT_SPEC.md) - 3/4/5페이지 포맷과 편집 규칙

## 입출력 계약

- [`contracts/market_pack.schema.json`](contracts/market_pack.schema.json)
- [`contracts/news_pack.schema.json`](contracts/news_pack.schema.json)
- [`contracts/editorial_memo.schema.json`](contracts/editorial_memo.schema.json)

## 현재 데모

`demo/2026-07-14_1430/`에는 공개 데이터와 연합인포맥스 공개 기사로 만든 시점 고정 데모가 있습니다.

- `nowhere_noon_brief_2026-07-14_1430KST.pptx`
- `nowhere_noon_brief_2026-07-14_1430KST.pdf`
- `market_pack.json`
- `news_pack.json`
- `editorial_memo.json`
- `source_manifest.md`
- `README.md` - 재생성법과 데모 편집 의도

데모는 제품의 **편집·구성 상한선**을 보여주기 위한 것이며, 실거래용 데이터 피드가 아닙니다.

## 데모 재생성

```bash
npm install
npm run build:demo
```

PPTX를 PDF로 바꾸는 과정은 LibreOffice 또는 사내 렌더러를 사용합니다.

## Phase 0 fixture bundle

현재 구현의 첫 목표는 PPTX 재현이 아니라, 고정 fixture를 검증하고 `PDF + buykings.kr` 게시 경로로 이어질 수 있는 briefing bundle을 만드는 것입니다.

```bash
python -m nowhere.cli brief build-fixture \
  --fixture demo/2026-07-14_1430 \
  --run-id 2026-07-14_1430
```

산출물은 `runs/<run-id>/`에 생성됩니다.

```text
runs/<run-id>/
  manifest.json
  market_pack.json
  news_pack.json
  editorial_memo.json
  charts/
    datawrapper_specs.json
    lightweight_series.json
  render/
    brief.html
  qa/
    validation_report.json
```

차트 경로는 기존 운영 도구를 우선합니다.

- Datawrapper: 게시용 정적 차트 spec
- lightweight-charts: `buykings.kr` 프론트에서 재사용할 시계열 payload

게시 전 cPanel 계획은 오케스트레이터 env를 우선 참조합니다. 기본 명령은 네트워크 업로드를 하지 않고 `cpanel_publish_result.json`만 씁니다.

```bash
python -m nowhere.cli brief publish-dry-run runs/2026-07-14_1430
python -m nowhere.cli brief publish-cpanel runs/2026-07-14_1430
```

실제 업로드는 `--execute`와 run ID 확인 문자열이 있을 때만 시도합니다. QA가 공개 가능 상태가 아니면 기본 차단됩니다. `--force`는 승인된 run에서만 review warning을 우회할 수 있고, draft는 우회하지 못합니다. `approve`는 `qa/approval_snapshot.json`에 승인 당시 입력 파일 해시를 남기며, 승인 이후 입력이 바뀌면 preflight와 cPanel execute가 차단됩니다. 결과 파일에는 `validation.ready_for_execute`, `validation.execute_complete`, 업로드 수, 실패 수가 기록됩니다.

```bash
python -m nowhere.cli brief approve runs/2026-07-14_1430 --by <name>
python -m nowhere.cli brief publish-cpanel runs/2026-07-14_1430 \
  --execute --confirm-execute 2026-07-14_1430
```

## Chart and source adapter contracts

차트 payload는 [docs/05_CHART_PAYLOAD_CONTRACTS.md](docs/05_CHART_PAYLOAD_CONTRACTS.md)에 고정합니다.

- `charts/datawrapper_specs.json`: Datawrapper 업로드에 가까운 table/config payload
- `charts/lightweight_series.json`: tracker/lightweight-charts 프론트용 series/options payload
- `publish/site/chart_bootstrap.js`: 게시 HTML에서 lightweight payload를 읽어 tracker chart를 렌더링하는 bootstrap

Datawrapper API 계획은 기본적으로 네트워크 호출 없이 `publish/datawrapper_plan.json`을 생성합니다. 결과 파일에는 `validation.ready_for_execute`, `validation.execute_complete`, `published_count`, 생성된 Datawrapper public URL 목록이 기록됩니다. `execute_complete`는 모든 차트가 생성, 데이터 업로드, publish 완료되고 각 차트의 public URL이 확보된 경우에만 true가 됩니다.

```bash
python -m nowhere.cli brief datawrapper-plan runs/2026-07-14_1430
```

실제 Datawrapper 차트 생성/데이터 업로드/publish는 승인된 run에서만, `--execute`와 run ID 확인 문자열이 있을 때만 시도합니다. QA review warning이 있으면 `--force`도 필요합니다.

```bash
python -m nowhere.cli brief datawrapper-plan runs/2026-07-14_1430 \
  --execute --confirm-execute 2026-07-14_1430 --force
```

실제 게시 전에는 `preflight`로 승인, QA, 파일 존재, Datawrapper/cPanel 실행 가능성을 한 번에 점검합니다.

```bash
python -m nowhere.cli brief preflight runs/2026-07-14_1430
python -m nowhere.cli brief preflight runs/2026-07-14_1430 --force
python -m nowhere.cli brief preflight runs/2026-07-14_1430 --force --probe-live
```

결과는 `publish/preflight_report.json`에 남고, 준비되지 않은 run은 CLI exit code `1`을 반환합니다. 보고서의 `execution_plan.commands`에는 preflight, Datawrapper execute, Datawrapper public URL verify, cPanel execute, buykings public URL verify, execution status 요약 순서의 실제 명령이 기록됩니다. `--probe-live`는 Datawrapper `/me`와 cPanel read-only 파일 목록 조회만 수행하며 업로드/차트 생성은 하지 않습니다.

```bash
python -m nowhere.cli brief datawrapper-probe
python -m nowhere.cli brief cpanel-probe
python -m nowhere.cli brief verify-datawrapper runs/2026-07-14_1430
python -m nowhere.cli brief verify-public runs/2026-07-14_1430
python -m nowhere.cli brief execution-status runs/2026-07-14_1430
```

Datawrapper execute는 생성, 데이터 업로드, publish 호출까지 수행한 뒤 `published_count`와 public URL을 기록하고 `publish/data/datawrapper_result.json`을 게시 bundle에 추가합니다. `verify-datawrapper`는 이 URL들을 read-only로 확인해 `publish/datawrapper_public_url_verification.json`을 남깁니다. cPanel execute는 Datawrapper execute와 URL verification이 완료된 run에서만 허용되며, 실행 직전에 chart contract, adapter validation, source audit blocker, publish manifest 파일 hash를 다시 검사합니다. cPanel execute는 업로드 뒤 `public_url_verification.json`으로 `buykings.kr` 공개 URL을 read-only 확인하며, 이 검증이 성공해야 `validation.execute_complete`와 `cpanel_execute_result.json` ledger가 남습니다. `execution-status`는 승인, preflight, Datawrapper execute/verify, cPanel execute/verify 상태를 `publish/execution_status.json`에 요약하며, 완료 ledger가 남지 않은 최신 실패 시도(`cpanel_publish_result.json`, `datawrapper_plan.json`)의 blocker도 함께 보여줍니다. 성공한 execute 결과는 `datawrapper_execute_result.json` / `cpanel_execute_result.json`에 보존되며, 같은 run 재실행은 기본 차단됩니다. 필요한 경우에만 `--allow-reexecute`를 명시합니다.

초기 source adapter는 `src/nowhere/sources/`에 있습니다.

- `JibiJsonlAdapter`: jibi 뉴스 JSONL fixture 입력
- `YFinanceAdapter`: `.[market]` extra 설치 후 글로벌 가격 fetch
- `NaverSnapshotAdapter`: fixture 기반 prototype, `public_web_restricted`와 재배포 제한 플래그 유지. collected `market_pack.indices`와 chart payload에도 `prototype_only`, `redistribution_allowed: false`, `rights_class`가 보존됩니다.

fixture adapter를 묶어 contract-valid 초안 pack을 만들 수 있습니다. yfinance 기반 `global_context`에는 `window_start`, `window_end`, `point_count`, `period`, `interval`이 남아 어떤 가격 window에서 계산됐는지 추적할 수 있습니다.

```bash
python -m nowhere.cli brief collect-fixtures --run-id collect-demo
python -m nowhere.cli brief source-audit runs/collect-demo/adapter_outputs
python -m nowhere.cli brief build-collected runs/collect-demo/adapter_outputs --run-id collect-demo-brief

# yfinance live smoke, still Naver/jibi fixture-based
python -m nowhere.cli brief collect-fixtures --run-id collect-live-yf \
  --live-yfinance --yfinance-ticker SPY --yfinance-ticker QQQ

# explicit Naver prototype URL mode
python -m nowhere.cli brief collect-fixtures --run-id collect-naver-live \
  --naver-url 'https://m.stock.naver.com/domestic/index/KOSPI/total'
```

산출물은 `runs/<run-id>/adapter_outputs/`에 생성됩니다.

```text
adapter_outputs/
  raw/
  observations/observations.json
  market_pack.json
  news_pack.json
  validation.json
  source_audit.json
  manifest.json
```

`source_audit.json`은 stale 관측값, Naver prototype/review-only 스냅샷과 재배포 제한, yfinance 약관 검토 플래그와 글로벌 가격 window 품질 플래그(`single_point_window`, `zero_window_start_price`), jibi source ID 누락과 뉴스 품질 플래그(`missing_market_links`, `missing_reported_claims`, `low_significance_hint`, `unverified_news_event`) 같은 운영 경고를 preflight에 전달합니다. collector가 만든 `manifest.json`에는 `adapter_contract.required_fields`가 함께 기록되며, `news_event`, `index_snapshot`, `global_price_latest` 중 누락된 필드가 있으면 source audit이 blocked가 되어 preflight도 발행을 차단합니다. `build-collected`는 adapter output의 `market_pack.json`/`news_pack.json`에 draft editorial memo를 붙여 Phase 0 publish bundle로 승격합니다.

## 권장 첫 구현 순서

```text
Phase 0  fixture 기반 정적 데모 재현
Phase 1  yfinance + OpenDART + jibi 어댑터
Phase 2  국내 장중 스냅샷 어댑터(Naver fallback 또는 KIS Open API)
Phase 3  market_pack/news_pack 자동 생성
Phase 4  GPT editorial_memo 수동 전달 루프
Phase 5  PPTX/PDF 렌더러와 QA
Phase 6  평가·회고 후 필요한 데이터만 추가
```

## 최소 실행 인터페이스 제안

```bash
# 1. 데이터 수집 및 RA 패킷 생성
python -m nowhere collect --as-of 2026-07-14T13:20:00+09:00

# 2. GPT 전문가 결과 저장 후 검증
python -m nowhere validate-editorial runs/2026-07-14/editorial_memo.json

# 3. 최신 숫자 재수집, stale-check, 최종 렌더링
python -m nowhere publish --run-id 20260714-1320 --format pptx,pdf
```

## 핵심 금지사항

- 출처와 기준시각 없는 숫자를 싣지 않습니다.
- 가격과 뉴스가 같은 시간에 움직였다는 이유만으로 인과관계를 확정하지 않습니다.
- 기사 수를 채우기 위해 중요하지 않은 뉴스를 넣지 않습니다.
- GPT가 수치를 임의로 수정하지 못하게 합니다.
- 사람 승인 후 시장 체제가 바뀌었는데도 그대로 발행하지 않습니다.
- 특정 리서치사의 디자인을 복제하지 않습니다. 정보 구조만 참고하고 독자적인 시각 체계를 사용합니다.
