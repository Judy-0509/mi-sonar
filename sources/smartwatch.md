---
name: smartwatch
kind: postgres
env: MI_DB_SMARTPHONE
tables: [sales_team.smartwatch_market_data]
summary: 스마트워치 시장 데이터 (TechInsights 단일 소스), 분기별 국가×업체 Sell-in
---
## 컬럼 의미

| column | 의미 | 비고 |
|---|---|---|
| id | 자동 번호 | |
| firm | 조사기관 | 현재 'TechInsights' 하나 |
| period | 분기 | 예: 2026Q3 |
| country | 국가 | |
| vendor | 업체 | Apple / Samsung / Huawei / Garmin / Fitbit / Others |
| sell_in_mu | Sell-in 수량 | 백만 대(Mu), 소수 가능 |
| published_month | 발행월 | DATE, 매월 1일. 같은 분기가 여러 발행월에 존재할 수 있음 = 개정 이력 |
| note | 문맥 메모 | |
| loaded_at | 적재 시각 | |

## 조사기관 (research firms)

- 기관 컬럼: `firm`
- 등록된 기관 목록:
  | 기관 | 커버리지 메모 |
  |---|---|
  | TechInsights | 분기별 국가×업체 Sell-in (단일 소스) |
- 기관이 하나뿐이므로 smartphone 의 "기관 혼합" 규칙은 적용되지 않는다.
- Others 는 나머지 합계이므로 업체 합산 시 Others 포함 여부를 명시한다.

## 개정 이력 규칙

- 같은 `period` 가 여러 `published_month` 값으로 존재할 수 있다. 발행월 필터 없는 SUM 은 중복 집계다.
- "최신 기준": (period, country, vendor) 별로 `published_month` 가 가장 큰 행을 사용한다.
- "지난번 대비 변동": 같은 `period` 의 두 `published_month` 값을 비교한다.
- 답변에 어느 `published_month` 를 사용했는지 반드시 밝힌다.

## 자주 쓰는 쿼리

```sql
-- 최신 발행 기준 분기별 전체 Sell-in
WITH latest AS (
  SELECT DISTINCT ON (period, country, vendor) period, country, vendor, sell_in_mu
  FROM sales_team.smartwatch_market_data
  ORDER BY period, country, vendor, published_month DESC
)
SELECT period, SUM(sell_in_mu) AS sell_in_mu
FROM latest GROUP BY period ORDER BY period

-- 특정 분기의 국가별 업체 점유율 (최신 발행 기준)
WITH latest AS (
  SELECT DISTINCT ON (period, country, vendor) period, country, vendor, sell_in_mu
  FROM sales_team.smartwatch_market_data
  WHERE period = '2026Q3'
  ORDER BY period, country, vendor, published_month DESC
)
SELECT country, vendor, sell_in_mu,
       ROUND(100.0 * sell_in_mu / SUM(sell_in_mu) OVER (PARTITION BY country), 1) AS share_pct
FROM latest ORDER BY country, sell_in_mu DESC

-- 같은 분기의 두 발행월 비교 (2026-07-01 vs 2026-10-01): vendor별 차이와 증감률
SELECT vendor, SUM(sell_in_mu) FILTER (WHERE published_month = DATE '2026-07-01') AS prev_mu,
       SUM(sell_in_mu) FILTER (WHERE published_month = DATE '2026-10-01') AS curr_mu,
       SUM(sell_in_mu) FILTER (WHERE published_month = DATE '2026-10-01')
       - SUM(sell_in_mu) FILTER (WHERE published_month = DATE '2026-07-01') AS diff_mu,
       ROUND(100.0 * (SUM(sell_in_mu) FILTER (WHERE published_month = DATE '2026-10-01')
       - SUM(sell_in_mu) FILTER (WHERE published_month = DATE '2026-07-01'))
       / NULLIF(SUM(sell_in_mu) FILTER (WHERE published_month = DATE '2026-07-01'), 0), 1) AS change_pct
FROM sales_team.smartwatch_market_data
WHERE period = '2026Q3' AND published_month IN (DATE '2026-07-01', DATE '2026-10-01')
GROUP BY vendor ORDER BY vendor

-- 특정 업체의 분기 추이 (최신 발행 기준)
WITH latest AS (
  SELECT DISTINCT ON (period, country, vendor) period, country, vendor, sell_in_mu
  FROM sales_team.smartwatch_market_data
  WHERE vendor = 'Apple'
  ORDER BY period, country, vendor, published_month DESC
)
SELECT period, SUM(sell_in_mu) AS sell_in_mu
FROM latest GROUP BY period ORDER BY period
```

## 주의사항

- 테이블은 DBaaS 팀에 생성 요청 중이며, 생성 전에는 `schema` 명령이 테이블을 찾지 못한다.
