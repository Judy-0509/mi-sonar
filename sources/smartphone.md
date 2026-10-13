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

## 자주 쓰는 쿼리 (컬럼명은 schema 출력에 맞춰 바꿀 것)

```sql
-- 분기별 총 출하량
SELECT quarter, SUM(shipments) AS shipments
FROM smartphone_market_data GROUP BY quarter ORDER BY quarter;

-- 특정 분기 제조사 점유율
SELECT vendor, SUM(shipments) AS s,
       ROUND(100.0 * SUM(shipments) / SUM(SUM(shipments)) OVER (), 1) AS share_pct
FROM smartphone_market_data WHERE quarter = '2026Q2'
GROUP BY vendor ORDER BY s DESC;

-- YoY: 같은 분기 전년 대비 (quarter 형식 'YYYYQn' 가정)
WITH q AS (
  SELECT quarter, SUM(shipments) s FROM smartphone_market_data GROUP BY quarter
)
SELECT a.quarter, a.s, b.s AS prev_year, ROUND(100.0 * (a.s - b.s) / b.s, 1) AS yoy_pct
FROM q a LEFT JOIN q b ON b.quarter = (LEFT(a.quarter, 4)::int - 1) || RIGHT(a.quarter, 2)
ORDER BY a.quarter;
```

## 주의사항

- 원본 파일 키 컬럼: `__KEY_COLUMN__` (사내 에이전트가 실제 컬럼명으로 교체) → `query.py fetch minio <키>`
- 수십만~수백만 행. 반드시 집계해서 가져온다.
