---
name: smartwatch
kind: postgres
env: MI_DB_SMARTPHONE
tables: [sales_team.smartwatch_market_data]
summary: 스마트워치 시장 데이터 (TechInsights 분기 실적·연간 전망, MI 자체 TAM), 국가×업체
---
## 컬럼 의미

| column | 의미 | 비고 |
|---|---|---|
| id | 자동 번호 | |
| dataset | 데이터 종류 | actual / forecast / our_tam (아래 설명). 쿼리 시 반드시 하나로 한정 |
| firm | 조사기관 | actual·forecast = 'TechInsights', our_tam = 'MI' |
| period | 기간 | actual·our_tam = 분기(예: 2026Q3), forecast = 연도(예: 2027) |
| country | 국가 | our_tam 은 항상 'Worldwide' |
| vendor | 업체 | Apple / Samsung / Huawei / Garmin / Fitbit / Others |
| sell_in_mu | Sell-in 수량 | 백만 대(Mu). actual·our_tam 은 필수, forecast 는 revenue_musd ÷ asp_usd 로 계산한 값 |
| revenue_musd | 매출 | 백만 달러. forecast 에만 있음 (그 외 NULL) |
| asp_usd | 평균판매가 | 달러. forecast 에만 있음 (그 외 NULL) |
| published_month | 발행월 | DATE, 매월 1일. 같은 기간이 여러 발행월에 존재할 수 있음 = 개정 이력 |
| note | 문맥 메모 | |
| loaded_at | 적재 시각 | |

## dataset 의미

- `actual`: TechInsights 분기 실적, 국가×업체 (period = 분기)
- `forecast`: TechInsights 연간 전망, 국가×업체 (period = 연도). sell_in_mu 는 revenue_musd ÷ asp_usd 로 도출한 값
- `our_tam`: MI 자체 분기 TAM, Worldwide×업체 (period = 분기, firm = 'MI')
- 서로 다른 dataset 을 합산하면 안 된다. 항상 `dataset = '...'` 로 한정한다.

## 조사기관 (research firms)

- 기관 컬럼: `firm`
- 등록된 기관 목록:
  | 기관 | 커버리지 메모 |
  |---|---|
  | TechInsights | actual(분기 실적), forecast(연간 전망) 국가×업체 |
  | MI | our_tam (자체 분기 TAM, Worldwide×업체) |
- dataset 별로 기관이 정해져 있어 smartphone 의 "기관 혼합" 규칙은 적용되지 않는다. 대신 dataset 을 섞지 않는다.
- Others 는 나머지 합계이므로 업체 합산 시 Others 포함 여부를 명시한다.

## 개정 이력 규칙

- 같은 `dataset`·`period` 가 여러 `published_month` 값으로 존재할 수 있다. 발행월 필터 없는 SUM 은 중복 집계다.
- "최신 기준": (dataset, period, country, vendor) 별로 `published_month` 가 가장 큰 행을 사용한다.
- "지난번 대비 변동": 같은 `dataset`·`period` 의 두 `published_month` 값을 비교한다.
- 답변에 어느 `published_month` 를 사용했는지 반드시 밝힌다.

## 자주 쓰는 쿼리

```sql
-- 최신 발행 기준 분기별 전체 Sell-in (actual)
WITH latest AS (
  SELECT DISTINCT ON (period, country, vendor) period, country, vendor, sell_in_mu
  FROM sales_team.smartwatch_market_data
  WHERE dataset = 'actual'
  ORDER BY period, country, vendor, published_month DESC
)
SELECT period, SUM(sell_in_mu) AS sell_in_mu
FROM latest GROUP BY period ORDER BY period

-- 특정 분기의 국가별 업체 점유율 (최신 발행 기준)
WITH latest AS (
  SELECT DISTINCT ON (period, country, vendor) period, country, vendor, sell_in_mu
  FROM sales_team.smartwatch_market_data
  WHERE dataset = 'actual' AND period = '2026Q3'
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
WHERE dataset = 'actual' AND period = '2026Q3' AND published_month IN (DATE '2026-07-01', DATE '2026-10-01')
GROUP BY vendor ORDER BY vendor

-- 특정 업체의 분기 추이 (최신 발행 기준)
WITH latest AS (
  SELECT DISTINCT ON (period, country, vendor) period, country, vendor, sell_in_mu
  FROM sales_team.smartwatch_market_data
  WHERE dataset = 'actual' AND vendor = 'Apple'
  ORDER BY period, country, vendor, published_month DESC
)
SELECT period, SUM(sell_in_mu) AS sell_in_mu
FROM latest GROUP BY period ORDER BY period

-- 연간 전망 (forecast) 업체별 Sell-in·매출·ASP (최신 발행 기준)
WITH latest AS (
  SELECT DISTINCT ON (period, country, vendor) period, country, vendor, sell_in_mu, revenue_musd, asp_usd
  FROM sales_team.smartwatch_market_data
  WHERE dataset = 'forecast'
  ORDER BY period, country, vendor, published_month DESC
)
SELECT period, vendor, SUM(sell_in_mu) AS sell_in_mu, SUM(revenue_musd) AS revenue_musd
FROM latest GROUP BY period, vendor ORDER BY period, vendor
```

## 주의사항

- 테이블은 DBaaS 팀에 생성 요청 중이며, 생성 전에는 `schema` 명령이 테이블을 찾지 못한다.
