# Data Sources and Acquisition Plan

작성 기준: 2026-07-14

## 1. 결론

첫 버전은 다음 다섯 축이면 충분하다.

```text
글로벌 가격        yfinance
한국시장 구조      KRX + pykrx/FinanceDataReader adapter
한국 장중 스냅샷   Naver prototype fallback, 이후 KIS Open API
기업 공시          OpenDART
뉴스               jibi + 공식자료 + GPT 웹 검증
거시·일정          FRED/BLS/BEA/ECOS/KOSIS
```

핵심은 각 영역에서 가장 많은 데이터를 주는 소스를 고르는 것이 아니라, **결과물 한 칸을 안정적으로 채울 소스를 정하고 대체 경로를 두는 것**이다.

## 2. 소스 우선순위 원칙

1. 공식 API 또는 공식 데이터
2. 계정 기반 공식 오픈 API
3. 공개 웹페이지·지연 데이터
4. 오픈소스 래퍼·스크래퍼
5. 수동 입력

각 필드는 다음처럼 우선순위를 가진다.

```yaml
KOSPI_INTRADAY:
  primary: kis_open_api
  prototype: naver_finance
  fallback: krx_delayed

KOSPI_DAILY_BREADTH:
  primary: krx
  adapter: pykrx

US_GLOBAL_PRICES:
  prototype: yfinance
  fallback: finance_data_reader
```

## 3. 추천 소스 상세

### 3.1 yfinance - 글로벌 가격 MVP

적합한 데이터:

- S&P500, NASDAQ, Dow, SOX, VIX
- S&P500·NASDAQ100 선물
- DXY, USD/KRW 프록시
- 미국 국채 수익률 프록시
- WTI, Brent, Gold, Copper
- Nikkei, Hang Seng, Shanghai, Taiwan
- 미국·한국 주요 종목 가격

조달 방식:

```python
import yfinance as yf

data = yf.download(
    ["^GSPC", "^IXIC", "^SOX", "CL=F", "DX-Y.NYB", "KRW=X"],
    period="5d",
    interval="5m",
    group_by="ticker",
)
```

장점:

- 설치와 사용이 간단함
- 여러 티커 일괄 다운로드
- 일봉과 장중 데이터를 같은 인터페이스로 처리
- prototype 속도가 빠름

제약:

- Yahoo의 공식 승인 API가 아님
- 프로젝트 문서상 연구·교육 목적이며 Yahoo 데이터는 개인 사용 용도로 안내됨
- 티커·시장별 지연, 누락, 간헐적 schema 변경 가능
- 사내 정규 배포 전 이용조건 검토 필요

권장 역할:

- 초기 데모와 내부 prototype
- 글로벌 가격의 빠른 1차 소스
- 핵심 값은 가능하면 다른 소스와 교차검증

공식 문서:

- https://ranaroussi.github.io/yfinance/

### 3.2 KRX Data Marketplace - 한국시장 공식 일별 구조

적합한 데이터:

- 전체지수 시세·등락률·구성종목
- 전 종목 시세·등락률·기본정보
- 투자자별 거래실적
- 종목별 투자자 거래실적과 순매수 상위
- 프로그램매매
- ETF 시세, 추적오차, 괴리율
- 선물 투자자별 거래, 베이시스, 옵션 IV·P/C ratio

조달 방식:

- 초기: 웹 조회 후 CSV 다운로드 또는 브라우저 어댑터
- 중기: 안정적인 호출 경로가 확인되면 전용 adapter
- 데이터 원본은 KRX, 파싱 로직은 별도로 관리

장점:

- 한국거래소 공식 데이터
- 시장 폭, 수급, ETF, 파생 구조를 넓게 확보
- 일별 검증 원장으로 적합

제약:

- 공개 메인 시장현황 일부는 20분 지연
- 웹 호출 방식이 변경될 수 있음
- 초단기 장중 시세의 핵심 소스로 보기 어려움
- 자동화·재배포 범위는 이용조건 검토 필요

권장 역할:

- 마감·일별 데이터의 source of truth
- 업종, 전 종목, 수급, 프로그램, ETF 구조
- 장중 prototype의 검증·보강

공식 사이트:

- https://data.krx.co.kr/contents/MDC/MAIN/main/index.cmd

### 3.3 pykrx - KRX/Naver adapter

적합한 데이터:

- KOSPI·KOSDAQ 종목 목록
- 일별 OHLCV
- 전 종목 시세
- 시가총액·기초지표
- 투자자 거래실적
- 지수와 구성종목

장점:

- Python으로 KRX 데이터를 빠르게 읽을 수 있음
- 개발 초기 fixture와 일별 배치에 편리

제약:

- KRX와 Naver를 스크래핑하는 비공식 라이브러리
- 공식 값과 차이가 날 수 있음
- 과도한 호출 시 차단 가능
- 상업적 사용 시 원 제공처 약관 준수 필요
- 장중 최종 투자자 데이터는 마감 후 제공되는 항목이 있음

권장 역할:

- 직접 원천이 아니라 KRX adapter 중 하나
- 실패 시 KRX 직접 다운로드 또는 대체 adapter로 전환 가능하게 설계

문서:

- https://github.com/sharebook-kr/pykrx

### 3.4 FinanceDataReader - 다중 시장 보조 adapter

적합한 데이터:

- KRX/KOSPI/KOSDAQ 종목 목록
- KOSPI·KOSDAQ·KOSPI200 지수
- 미국·아시아 지수
- 개별 종목 가격
- FRED 시계열 연결

장점:

- 국내외 가격과 listing을 같은 인터페이스로 처리
- CSV/JSON fixture 생성에 편리
- KRX 지수 구성종목 snapshot 기능

제약:

- 내부적으로 여러 웹 원천에 의존
- 원천별 이용조건과 안정성이 다름
- 실시간 source of truth로 사용하지 않음

권장 역할:

- yfinance 또는 pykrx 장애 시 보조
- 종목 master와 과거 데이터 fixture

문서:

- https://github.com/FinanceData/FinanceDataReader

### 3.5 Naver Finance snapshot - prototype 전용 국내 장중

적합한 데이터:

- KOSPI·KOSDAQ 현재가, 시가·고가·저가
- 거래량·거래대금
- 투자자별 누적 수급
- 프로그램 수급
- 상승·보합·하락 종목 수
- 시가총액 상위 종목 등락
- 은행 고시환율 프록시

조달 방식:

- HTML snapshot parser
- 반드시 페이지에 표시된 기준시각 저장
- 원문 HTML을 raw artifact로 보관

장점:

- 별도 계정 없이 빠른 prototype 가능
- 한 페이지에서 MVP에 필요한 다수 지표 확보

제약:

- 제공 정보가 지연되거나 오류가 있을 수 있음
- 게시 정보 무단 배포 제한 문구가 있음
- 환율은 서울 현물환 체결가가 아니라 은행 고시환율일 수 있음
- 장기 운영이나 외부 배포의 정식 소스로 사용하지 않음

권장 역할:

- `prototype_only`
- 내부 데모와 개발 fixture
- production에서는 KIS 또는 계약 데이터로 교체

### 3.6 KIS Open API - 국내 장중의 권장 업그레이드

적합한 데이터:

- 국내주식 현재가와 호가
- 국내주식 실시간 체결·호가 WebSocket
- 국내선물옵션
- ETF·해외주식 등 계정 범위 내 API

조달 방식:

- 한국투자증권 계정과 앱키·앱시크릿 발급
- REST snapshot + WebSocket subscription
- 공식 GitHub sample을 adapter skeleton으로 사용

장점:

- 공식 오픈 API
- REST와 WebSocket 지원
- 실시간 호가·체결 예제 제공
- Naver/스크래퍼보다 장기 운영에 적합

제약:

- 계정·인증·호출한도 관리 필요
- 투자자별 시장 전체 수급과 시장 폭은 별도 소스가 필요할 수 있음
- 운영계·모의계 환경 차이 확인 필요

권장 역할:

- Phase 1.5 이후 국내 실시간 시세의 primary
- Naver snapshot을 대체

공식 문서:

- https://apiportal.koreainvestment.com/intro
- https://github.com/koreainvestment/open-trading-api

### 3.7 OpenDART - 기업 공시

적합한 데이터:

- 공시 검색
- 기업 개황
- 공시 원문 파일
- 기업 고유번호와 종목코드 매핑
- 실적, 공급계약, 자사주, 유상증자, 지분 변동

조달 방식:

- API key 발급
- 1-5분 주기 incremental polling
- 중요 공시 유형 whitelist
- `corp_code` master를 정기 갱신

장점:

- 금융감독원 공식 공시
- 뉴스보다 앞선 공식 사실 소스
- 기업 이벤트의 기준 원장

제약:

- 공시 문서 구조가 유형별로 다름
- XML/HTML 원문 파싱 규칙 필요
- 수정 공시와 정정 공시 버전 관리 필요

공식 문서:

- https://opendart.fss.or.kr/guide/main.do?apiGrpCd=DS001

### 3.8 FRED - 미국 금리·거시 시계열과 발표일

적합한 데이터:

- 미국 2년·10년 국채
- 장단기 스프레드
- 금융여건·달러·신용 지표
- CPI/PCE/고용 등 과거 시계열
- release dates
- ALFRED vintage 데이터

조달 방식:

- API key
- 매일 배치 + 발표 직후 갱신
- series ID를 config로 관리

장점:

- 세인트루이스 연은 공식 API
- 시계열과 release metadata를 구조화해 제공
- 과거 시점 데이터 vintage 관리 가능

제약:

- 실시간 시장 틱 데이터가 아님
- 원자료 발표기관과 시차가 있을 수 있음

공식 문서:

- https://fred.stlouisfed.org/docs/api/fred/

### 3.9 BLS·BEA - 미국 경제지표와 공식 일정

BLS:

- CPI, 고용, PPI, JOLTS
- 공식 release calendar
- Public Data API v1/v2

BEA:

- GDP, PCE, 개인소득·지출
- 공식 release schedule
- API와 metadata

권장 방식:

- 발표 일정은 각 기관의 공식 달력을 우선
- 지표 수치는 발표 직후 공식 API·release에서 수집
- 뉴스 요약은 보조로만 사용

공식 문서:

- https://www.bls.gov/developers/
- https://www.bls.gov/schedule/
- https://apps.bea.gov/api/signup/

### 3.10 ECOS·KOSIS - 한국 거시

ECOS:

- 한국은행 기준금리, 시장금리, 환율, 통화·신용, 경기지표

KOSIS:

- 산업활동, 고용, 물가, 인구 등 국가통계
- 통계표, 통계설명, 주요지표 API

권장 역할:

- 일별 시황의 상시 숫자보다는 정책·거시 스토리의 공식 근거
- 발표 일정과 이전치·장기 추세 데이터

공식 문서:

- https://ecos.bok.or.kr/api/
- https://kosis.kr/openapi/index/index.jsp

### 3.11 CoinGecko - 선택적 크립토

적합한 데이터:

- BTC·ETH 현물 가격
- 거래량·시가총액
- 시장 전반 위험선호 보조지표

장점:

- REST, WebSocket, Webhook
- 무료 Demo API 존재

제약:

- 무료 plan의 endpoint와 rate limit 제한
- 국내 주식 시황에서 중요할 때만 노출

공식 문서:

- https://docs.coingecko.com/

### 3.12 Alpha Vantage - 선택적 일정·대체 데이터

적합한 데이터:

- Earnings Calendar CSV
- 일부 FX·원자재·기술지표

제약:

- 다수 intraday와 고급 기능이 premium
- 핵심 가격 소스로 쓰기보다 일정·fallback 용도

공식 문서:

- https://www.alphavantage.co/documentation/

## 4. jibi 뉴스 입력 계약

jibi는 기사 전체를 GPT에 밀어 넣는 역할이 아니다. 다음 두 가지를 제공한다.

### 4.1 실시간 후보 이벤트

```json
{
  "event_id": "evt-20260714-001",
  "first_seen_at": "2026-07-14T08:56:00+09:00",
  "title": "SK하이닉스 실적 기대치 재조정",
  "category": "earnings_expectation",
  "entities": ["SK하이닉스", "한국투자증권"],
  "tickers": ["000660"],
  "facts": [
    "2분기 영업이익 추정치가 컨센서스보다 낮게 제시됨",
    "메모리 업종 비중확대 의견은 유지됨"
  ],
  "sources": ["jibi://article/123", "dart://..."],
  "rights_class": "internal_derived"
}
```

### 4.2 온디맨드 맥락 검색

- 같은 기업의 이전 실적 가이던스
- 지난 6개월 유사 정책 발언
- 동일 이슈의 후속 기사
- 관련 해외 원문
- 반대 해석을 제시한 기사

## 5. MVP 데이터 카탈로그

| 그룹 | 필드 | 1차 소스 | 보조 소스 | 주기 | 페이지 |
|---|---|---|---|---|---|
| 국내지수 | KOSPI 현재·시가·고저·전일 | KIS/Naver | KRX | 1-5분 | 1,2 |
| 국내지수 | KOSDAQ 현재·시가·고저·전일 | KIS/Naver | KRX | 1-5분 | 1,2 |
| 시장 폭 | 상승·보합·하락 종목 수 | Naver/KRX | 자체 계산 | 5분 | 1,2 |
| 수급 | 외국인·기관·개인 KOSPI | Naver/KRX | 증권사 API | 5분 | 2 |
| 수급 | 외국인·기관·개인 KOSDAQ | Naver/KRX | 증권사 API | 5분 | 2 |
| 프로그램 | 차익·비차익 | Naver/KRX | - | 5분 | 2 |
| 종목 | 시총 상위 10개 등락 | KIS/Naver | yfinance | 5분 | 1,2 |
| 업종 | 업종별 등락 | KRX | pykrx | 10분 | 2 |
| 환율 | USD/KRW | KIS/공식 FX | Naver/yfinance | 5분 | 1 |
| 미국 | S&P500·NASDAQ·SOX 전일 | yfinance | FDR | 일 1회 | 1 |
| 선물 | S&P500·NASDAQ100 선물 | yfinance | 대체 API | 5분 | 1,3 |
| 금리 | 미국 10년 | yfinance/FRED | FDR | 5-15분 | 1,3 |
| 달러 | DXY | yfinance | FDR | 5-15분 | 1,3 |
| 원자재 | WTI·Brent·Gold | yfinance | Alpha Vantage | 5-15분 | 1,3 |
| 아시아 | Nikkei·Hang Seng·Shanghai·Taiwan | yfinance/FDR | - | 15분 | 3 |
| 공시 | 중요 DART 공시 | OpenDART | jibi | 1-5분 | 3 |
| 뉴스 | 사건 클러스터 10-15개 | jibi | GPT web | 실시간 | 3-5 |
| 일정 | BLS·BEA·Fed·기업 IR | 공식 캘린더 | Alpha Vantage | 일 1회 | 3,5 |

## 6. 소스별 품질등급

```text
A  공식 API·공식 발표
B  공식 웹·계정 기반 공식 Open API
C  공개 웹 snapshot
D  오픈소스 wrapper/scraper
E  수동 입력
```

동일한 숫자라도 `quality_grade`를 보존한다.

## 7. 실패·대체 규칙

예시:

```text
KIS 실패
  -> Naver snapshot 사용
  -> 헤더에 prototype fallback 경고

KRX 업종 수급 실패
  -> 이전 실행값을 사용하지 않음
  -> 해당 표를 삭제하고 '수급 데이터 미확보' 표시

yfinance 글로벌 선물 실패
  -> FDR 또는 이전 종가만 사용
  -> 실시간이라고 표시하지 않음

jibi 지연
  -> OpenDART와 공식 일정만 사용
  -> 뉴스 페이지에 cutoff 경고
```

## 8. 조달 우선순위

### 즉시 구현

- yfinance
- OpenDART
- FRED
- jibi input contract
- Naver snapshot prototype

### 2차 구현

- KRX daily/market structure
- pykrx/FDR adapter
- official release calendars

### 필요성이 확인되면

- KIS Open API WebSocket
- 뉴스 반응 1/5/15/30분 측정
- ETF·파생 구조
- CoinGecko

## 9. 데이터 권리와 기록

각 artifact에는 다음을 기록한다.

```text
source_url
retrieved_at
market_as_of
rights_class
redistribution_note
raw_file_hash
parser_version
```

추천 `rights_class`:

- `public_official`
- `public_web_restricted`
- `open_source_adapter`
- `internal_licensed`
- `internal_derived`
- `publication_safe`

최종 PDF에는 원문 전문이나 캡처를 무분별하게 재사용하지 않고, 숫자·사실·파생 차트와 짧은 출처 표기를 중심으로 구성한다.
