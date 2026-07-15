# Demo 2026-07-14 14:30 KST

이 폴더는 `market_pack.json`, `news_pack.json`, `editorial_memo.json` 세 계약을 이용해 만든 5페이지 고정 데모입니다.

## 파일

- `market_pack.json`: 공개 장중 스냅샷과 파생 수치
- `news_pack.json`: 사건 단위 뉴스와 일정
- `editorial_memo.json`: 제목, 불릿, 심층 스토리, 진행자 질문
- `build_demo.js`: 위 JSON을 읽어 PPTX를 생성하는 독립 예제
- `nowhere_noon_brief_2026-07-14_1430KST.pptx`: 편집 가능한 결과물
- `nowhere_noon_brief_2026-07-14_1430KST.pdf`: 배포·검토용 결과물
- `source_manifest.md`: 사용 소스와 한계

## 재생성

저장소 루트에서:

```bash
npm install
npm run build:demo
```

PDF 변환은 LibreOffice 또는 사내 렌더러에서 수행합니다.

```bash
libreoffice --headless --convert-to pdf \
  --outdir demo/2026-07-14_1430 \
  demo/2026-07-14_1430/nowhere_noon_brief_2026-07-14_1430KST.pptx
```

## 데모 해석

이 데모의 중심 대비는 다음과 같습니다.

```text
KOSPI +1.61%, 장중 저점 대비 +7.3%
vs
KOSPI 상승 종목 비율 30.9%, KOSDAQ -2.08%
```

따라서 `지수 반등`을 `시장 전체 안정`과 구분하고, 반도체 업황은 `붕괴`보다 `단기 기대치·수급 재조정` 프레임으로 설명했습니다. 공개 snapshot 기반이라 production data feed로 사용하면 안 됩니다.
