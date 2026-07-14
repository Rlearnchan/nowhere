# Nowhere — 시황 라이브 참고 자료 허브

`nowhere`는 시황 라이브를 준비할 때 쓰는 참고 자료, 링크, 기사 메모, 차트/지표 요약, 방송 전 체크리스트를 모으는 리포입니다.

## 목적

- 라이브 전 참고 자료를 한 곳에 모은다.
- 기사/리포트/데이터 출처와 사용 여부를 분리해서 기록한다.
- 방송용 메모와 원본 자료를 구분한다.
- 나중에 `shorts`, `syuka-ops`, `tracker`와 연결할 수 있게 날짜 기준 구조를 유지한다.

## 기본 구조

```text
references/
  YYYY-MM-DD/
    README.md
    links.md
    market_brief.md
    talking_points.md
    source_notes.md
  raw/          # Git 제외: 원본 PDF, 캡처, 대용량 파일
  archive/      # Git 제외: 오래된 원본 묶음
scripts/
  README.md
schemas/
  reference_item.schema.json
templates/
  daily_live_pack.md
```

## 원칙

- 원문 기사/리포트 전문을 복사하지 않고 링크, 짧은 인용, 요약, 사용 메모를 남긴다.
- 투자 조언처럼 보이는 표현은 방송 메모 단계에서 분리해 검토한다.
- 출처, 작성 시각, 확인 시각, 방송 사용 여부를 남긴다.
- 대용량 원본 파일과 DB는 Git에 올리지 않는다.

## 빠른 시작

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -e '.[dev]'
nowhere init-day --date 2026-07-14 --title '시황 라이브 준비'
```
