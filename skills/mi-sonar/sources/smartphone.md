---
name: smartphone
kind: postgres
env: MI_DB_SMARTPHONE
tables: [smartphone_market_data]
summary: 스마트폰 시장 데이터 (모델/출하량/점유율 등)
---
## 컬럼 의미

| column | 의미 | 비고 |
|---|---|---|
| __사내 에이전트가 `query.py schema smartphone` 출력으로 채움__ | | |

## 조사기관 (research firms)

- 기관 컬럼: `__FIRM_COLUMN__` (사내 에이전트가 실제 컬럼명으로 교체)
- 등록된 기관 목록 (적재 시 표기 통일됨):
  | 기관 | 커버리지 메모 |
  |---|---|
  | __사내 에이전트가 `SELECT DISTINCT <기관컬럼>` 결과로 채움__ | |
- 적재 규칙: 기관명 표기, 기간 형식(예: 2026Q2), 단위는 적재 시 통일한다. 에이전트가 쿼리에서 보정하지 않는다.
- 같은 모델·기간 행이 기관 수만큼 존재한다. 기관으로 필터하지 않은 SUM은 중복 집계다.

## 기관 혼합 규칙 (요약; 절차는 SKILL.md 4단계)

- 같은 기관: 숫자를 직접 더하고 뺀다. 주기 변환(weekly→monthly)으로 빠진 항목을 상위 묶음에서 분리할 수 있다.
- 다른 기관: 비율만 가져온다. 추정 = 기준 기관의 분모 값 × (타 기관 대상 ÷ 타 기관 분모).
- 추정값은 저장하지 않는다. 답변에 `(추정)` 과 계산식을 붙인다.
- 혼합에 필요한 컬럼: 기관 `__FIRM_COLUMN__`, 주기(weekly/monthly 구분), 지역, 모델, 기간. 컬럼 의미 표에 어떤 컬럼이 주기·지역인지 적어 둔다.

## 자주 쓰는 쿼리 (컬럼명은 schema 출력에 맞춰 바꿀 것)

```sql
-- 분기별 총 출하량
SELECT quarter, SUM(shipments) AS shipments
FROM smartphone_market_data WHERE <기관컬럼> = '<기관>'
GROUP BY quarter ORDER BY quarter;

-- 특정 분기 제조사 점유율
SELECT vendor, SUM(shipments) AS s,
       ROUND(100.0 * SUM(shipments) / SUM(SUM(shipments)) OVER (), 1) AS share_pct
FROM smartphone_market_data WHERE quarter = '2026Q2' AND <기관컬럼> = '<기관>'
GROUP BY vendor ORDER BY s DESC;

-- YoY: 같은 분기 전년 대비 (quarter 형식 'YYYYQn' 가정)
WITH q AS (
  SELECT quarter, SUM(shipments) s FROM smartphone_market_data
  WHERE <기관컬럼> = '<기관>' GROUP BY quarter
)
SELECT a.quarter, a.s, b.s AS prev_year, ROUND(100.0 * (a.s - b.s) / b.s, 1) AS yoy_pct
FROM q a LEFT JOIN q b ON b.quarter = (LEFT(a.quarter, 4)::int - 1) || RIGHT(a.quarter, 2)
ORDER BY a.quarter;
```

## 주의사항

- 원본 파일 키 컬럼: `__KEY_COLUMN__` (사내 에이전트가 실제 컬럼명으로 교체) → `query.py fetch minio <키>`
- 수십만~수백만 행. 반드시 집계해서 가져온다.
