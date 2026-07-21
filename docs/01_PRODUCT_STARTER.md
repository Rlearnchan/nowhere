# NOWHERE NOON BRIEF - Product Starter

## 1. 제품 한 문장

> 공개 시장 데이터와 jibi 뉴스 원장을 바탕으로, Codex가 사실과 차트를 준비하고 GPT 전문가가 중요도·인과 후보·반론을 편집한 뒤, 사람이 승인해 3-5페이지 장중 시황 보조자료로 발행하는 시스템.

## 2. 왜 이 제품을 만드는가

장중 라이브에 필요한 것은 뉴스 목록이나 차트 묶음이 아니다. 진행자는 짧은 시간 안에 다음 네 가지를 알아야 한다.

1. 지금 시장이 어떤 상태인가.
2. 무엇이 실제로 움직이고 있는가.
3. 어떤 설명이 가장 설득력 있고, 무엇은 아직 가설인가.
4. 오후에 어떤 조건을 보면 판단을 바꿔야 하는가.

기존 자동화는 수집량을 늘리기 쉽지만, 수집량이 늘수록 편집 부담도 함께 증가한다. 이 프로젝트는 **자료를 많이 모으는 시스템**이 아니라 **판단에 필요한 증거를 적절한 밀도로 압축하는 시스템**을 목표로 한다.

## 3. 참고자료에서 가져온 설계 원리

### 신한 Daily Market Digest에서 가져올 것

- 첫 페이지에서 한국·미국·FICC의 핵심 수치를 한 번에 훑는 구조
- 한국시장 페이지에서 지수, 업종, 수급, 종목을 같은 화면에 배치하는 방식
- 수익률 표와 작은 차트를 결합해 비교 비용을 낮추는 방식

가져오지 않을 것:

- 매일 모든 국가와 모든 자산을 고정으로 싣는 높은 밀도
- 1D·1W·1M·YTD를 모든 표에 반복하는 구성
- 특정 증권사의 시각적 자산이나 레이아웃 복제

### Market Radar에서 가져올 것

- 숫자보다 먼저 읽히는 편집된 제목
- 짧은 문장으로 시장의 중심 논지를 세우는 방식
- 한 페이지 안에서 지수·환율·업종을 하나의 이야기로 묶는 방식

### 장중 급락 분석 보고서에서 가져올 것

- 직접 트리거와 배경 취약성을 분리
- 펀더멘털 요인과 수급·레버리지 증폭 요인을 분리
- 대안 가설과 반론을 함께 기록
- 전망보다 판단을 바꿀 조건을 제시

### autopark 운영본에서 가져올 것

- 넓은 원자료 수집, 차트 생성, 로그, QA, 아카이브
- 진행자용 요약과 근거 원장을 분리하는 사고방식

가져오지 않을 것:

- 수집한 모든 자료를 최종 산출물에 노출하는 방식
- 30페이지가 넘는 원자료 팩을 진행자에게 그대로 전달하는 방식

### 정책·이벤트 보고서에서 가져올 것

- 발표 내용과 시장 함의를 분리
- 장기 계획, 확정 집행액, 중복 가능성을 구분
- 실행 조건과 제약을 별도의 체크포인트로 정리

## 4. 제품 철학

### 4.1 Output-first

데이터 목록을 먼저 무한히 확장하지 않는다. 기본 4페이지를 먼저 고정하고, 실제로 반복해서 쓰이는 데이터만 수집한다.

### 4.2 판단 자체보다 판단의 전후를 자동화

```text
Codex: 수집 - 정규화 - 계산 - 차트 - 근거 패킷
GPT: 중요도 - 원인 후보 비교 - 반론 - 스토리 - 질문
사람: 최종 논지 - 공개 문구 - 발행 승인
Codex: 최신값 교체 - 자료화 - QA - 아카이브
```

### 4.3 사실·해석·가설의 분리

문장마다 다음 중 하나의 성격을 가져야 한다.

- `observed_fact`: 가격, 수급, 공시처럼 직접 확인된 사실
- `reported_claim`: 기사나 리서치가 주장한 내용
- `interpretation`: 복수 근거를 바탕으로 한 해석
- `hypothesis`: 아직 확인이 필요한 원인 후보
- `counterevidence`: 주된 해석과 맞지 않는 증거
- `disconfirmation_condition`: 판단을 바꿀 조건

### 4.4 인과관계 절제

뉴스 발생 시각과 가격 움직임이 겹쳐도 자동으로 원인이라 부르지 않는다.

최소한 다음을 확인한다.

- 가격이 뉴스보다 먼저 움직였는가.
- 시장·업종 전체가 같은 방향이었는가.
- 거래대금이나 수급 변화가 동반됐는가.
- 공식 발표 또는 복수 소스가 사실을 확인하는가.
- 더 단순한 대안 설명이 있는가.

### 4.5 기본값은 4페이지

- 3페이지: 조용한 날
- 4페이지: 일반적인 날
- 5페이지: 급락, 정책, 실적, 지정학 이벤트일

페이지를 채우기 위해 이야기를 만들지 않는다.

## 5. 기본 산출물

### 5.1 공개·진행자용 PDF/PPTX

- 읽는 시간 5분 이내
- 기본 4페이지, 최대 5페이지
- 숫자·차트·뉴스·스토리·질문을 포함
- 각 페이지에 기준시각과 출처 표시

### 5.2 내부 근거 원장

- 원본 수집 결과
- 정규화 JSON/Parquet
- 뉴스 이벤트 클러스터
- 웹 검색 추가 출처
- claim-evidence map
- QA 로그

### 5.3 구조화 계약

- `market_pack.json`: 정량 상태와 차트
- `news_pack.json`: 사건 단위 뉴스와 공식 근거
- `editorial_memo.json`: GPT 전문가의 편집 결과
- `publication_manifest.json`: 최종 페이지와 사용 근거

## 6. 권장 아키텍처

```text
[yfinance / KRX / KIS / OpenDART / FRED / jibi]
                         |
                         v
                 source adapters
                         |
                         v
                 raw immutable store
                         |
                         v
             normalize + quality checks
                         |
                         v
        market_pack.json + news_pack.json
                         |
                 human candidate review
                         |
                         v
                  GPT expert session
                         |
                         v
                 editorial_memo.json
                         |
                  human approval gate
                         |
                         v
              final refresh + stale check
                         |
                         v
             PPTX / PDF / source manifest
```

## 7. 구현해야 할 모듈

### 7.1 Source adapters

```text
src/sources/yfinance_adapter.py
src/sources/krx_adapter.py
src/sources/naver_snapshot_adapter.py
src/sources/kis_adapter.py
src/sources/opendart_adapter.py
src/sources/fred_adapter.py
src/sources/jibi_adapter.py
```

공통 인터페이스:

```python
class SourceAdapter(Protocol):
    def fetch(self, request: SourceRequest) -> RawArtifact: ...
    def normalize(self, raw: RawArtifact) -> list[Observation]: ...
    def healthcheck(self) -> SourceHealth: ...
```

### 7.2 Normalized data model

모든 관측값은 최소한 다음 필드를 가진다.

```text
source_id
field_name
instrument_id
value
unit
market_as_of
captured_at
source_system
quality_flags
rights_class
```

### 7.3 Feature calculators

MVP 계산은 단순해야 한다.

- 전일 대비 수익률
- 시가 대비 수익률
- 장중 저점 대비 회복률
- 장중 범위 내 현재 위치
- 상승·하락 종목 비율
- KOSPI와 KOSDAQ 괴리
- 외국인·기관·프로그램 수급 요약
- 업종·대표 종목 상대강도
- 뉴스 전후 시장 반응은 데이터가 안정된 뒤 추가

### 7.4 News event builder

기사 단위가 아니라 사건 단위로 묶는다.

```text
10개 기사
  -> 반도체 실적 기대치 재조정 이벤트 1개
  -> 레버리지 ETF 정책 대응 이벤트 1개
```

필수 기능:

- 제목 정규화
- 종목·기관 엔티티 연결
- 유사 기사 클러스터링
- 최초 수신시각 유지
- 공식 자료 연결
- 중복·후속 기사 버전 관리

### 7.5 GPT expert handoff

GPT에는 원본 기사 수백 건을 보내지 않는다.

입력:

- 정량 시장 상태
- 후보 이벤트 10-15개
- 공식 사실
- 충돌하는 데이터
- 열린 질문

출력:

- 편집 제목
- 한 줄 시장 요약
- 뉴스 불릿
- 심층 스토리 1-2개
- 대안 가설과 반론
- 오후 체크포인트
- 진행자 질문
- 추가 데이터 요청

### 7.6 Renderer

권장 구성:

```text
PptxGenJS -> PPTX
LibreOffice -> PDF
PNG render -> visual QA
```

렌더러는 텍스트를 새로 해석하지 않고, 승인된 editorial memo와 최신 숫자를 배치한다.

### 7.7 QA

#### Data QA

- 기준시각 누락
- 오래된 값
- 단위 혼재
- 전일값이 장중값으로 남아 있음
- 수급 합계 부호 이상
- 소스 간 핵심 지수값 과도한 불일치

#### Editorial QA

- 숫자 없는 정량 표현
- 근거 ID 없는 인과 주장
- 사실과 해석의 혼합
- 과도한 확신 표현
- 반론·조건 누락

#### Layout QA

- 글자 잘림
- 표·차트 겹침
- 출처 글자 누락
- 깨진 한글
- 페이지 수 초과

## 8. 권장 저장소 구조

```text
nowhere-noon/
  README.md
  pyproject.toml
  config/
    instruments.yaml
    source_priority.yaml
    editorial_rules.yaml
  src/nowhere/
    sources/
    normalize/
    features/
    news/
    contracts/
    render/
    qa/
    cli.py
  contracts/
  prompts/
    expert_system.md
    expert_task.md
  templates/
    noon_brief.pptx
  fixtures/
    2026-07-14/
  tests/
    unit/
    integration/
    visual/
  runs/
    YYYY-MM-DD/
      raw/
      normalized/
      handoff/
      editorial/
      publication/
      audit/
```

## 9. 일일 운영 흐름

```text
11:40  1차 시장·뉴스 수집
11:50  Codex 정량 요약과 후보 이벤트 생성
12:00  사람의 후보 선별
12:05  GPT 전문가 분석
12:25  사람의 제목·논지 승인
12:40  데이터 재수집
12:45  stale-check
12:50  PPTX/PDF 생성
13:00  숫자·문장·출처 QA
13:10  진행자 전달
```

방송 시간에 맞춰 13:20 또는 13:40로 옮길 수 있지만, 단계 간 책임은 유지한다.

## 10. 단계별 구현 로드맵

### Phase 0 - 데모 재현

- 제공된 데모 JSON으로 PPTX/PDF 생성
- 외부 네트워크 없이 재현 가능
- 시각 회귀 테스트 구축

### Phase 1 - 공개 데이터 최소 파이프라인

- yfinance 글로벌 시장
- OpenDART 공시
- FRED 미국 금리·매크로
- jibi 뉴스 입력 계약
- Naver snapshot prototype fallback

### Phase 2 - 한국시장 구조 보강

- KRX 일별 전 종목·업종·수급
- KIS Open API 실시간 시세 옵션
- 업종과 대표 종목 테이블

### Phase 3 - 전문가 루프

- market/news pack 생성
- GPT 입력 프롬프트
- editorial memo 검증
- 추가 데이터 요청과 보충 패킷

### Phase 4 - 운영·평가

- 인간 편집 시간
- 사용된 뉴스 비율
- 숫자 오류
- 인과 주장 수정률
- 진행자 만족도
- 방송 후 판단 적중이 아니라 **설명력과 조건의 유용성** 평가

## 11. MVP 완료 기준

- 4페이지 결과물을 매일 30분 이내에 만들 수 있다.
- 국내외 핵심 지수, 환율, 업종, 수급, 주요 종목이 들어간다.
- 뉴스는 사건 단위 6-8개만 노출된다.
- 심층 스토리 1개 이상이 사실-해석-반론-조건 구조를 가진다.
- 모든 숫자에 기준시각과 소스가 있다.
- 사람이 승인하기 전에는 발행되지 않는다.
- 소스 실패가 결과물 상단에 명확히 표시된다.
