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

## 자료(슬라이드)용 집계

### 지역 구분 (5개)

| 지역 | 국가 (country 값) |
|---|---|
| 북미 | United States, USA, US, Canada |
| 유럽 | Germany, France, United Kingdom, UK, Italy, Spain, Netherlands, Sweden, Poland, Switzerland, Western Europe, Eastern Europe, Europe |
| 중국 | China |
| 아시아(중국 제외) | Japan, South Korea, Korea, India, Taiwan, Indonesia, Vietnam, Thailand, Philippines, Malaysia, Australia, Asia Pacific, APAC |
| 기타 | 위에 없는 모든 국가 (Latin America, Brazil, Mexico, Middle East, Africa, MEA, Rest of World 포함) |

쿼리에 붙여 쓰는 CASE:

```sql
CASE
  WHEN country IN ('United States', 'USA', 'US', 'Canada') THEN '북미'
  WHEN country IN ('Germany', 'France', 'United Kingdom', 'UK', 'Italy', 'Spain', 'Netherlands', 'Sweden', 'Poland', 'Switzerland', 'Western Europe', 'Eastern Europe', 'Europe') THEN '유럽'
  WHEN country = 'China' THEN '중국'
  WHEN country IN ('Japan', 'South Korea', 'Korea', 'India', 'Taiwan', 'Indonesia', 'Vietnam', 'Thailand', 'Philippines', 'Malaysia', 'Australia', 'Asia Pacific', 'APAC') THEN '아시아(중국 제외)'
  ELSE '기타'
END
```

규칙: 국가명은 위 표의 TechInsights 표기와 정확히 일치해야 한다. 사내 에이전트는 적재 1회당 '기타'로 떨어졌지만 기타 목록에 없는 국가를 나열하고, 표 확장은 담당자가 한다. 지역을 추측해서 배정하지 않는다.

### 우리 TAM 연간 (vendor별)

```sql
WITH latest AS (
  SELECT DISTINCT ON (period, vendor) period, vendor, sell_in_mu
  FROM sales_team.smartwatch_market_data
  WHERE dataset = 'our_tam' AND country = 'Worldwide' AND firm = 'MI'
  ORDER BY period, vendor, published_month DESC
)
SELECT LEFT(period, 4) AS year, vendor, SUM(sell_in_mu) AS tam_mu, COUNT(*) AS quarters
FROM latest
WHERE LEFT(period, 4) BETWEEN '2025' AND '2031'
GROUP BY 1, 2 ORDER BY 1, 2
```

`quarters` 가 4 가 아닌 연도는 일부 분기만 있는 값이므로 답변에 그 사실을 반드시 밝힌다.

### 지역별 판매 비중 + 전년比 (YTD)

아래 SQL 의 연도 리터럴 `'2026'` 은 올해로 바꿔 쓴다 (전년은 `'2025'`). 올해 데이터가 있는 분기만, 전년 같은 분기 번호와 비교한다.

```sql
WITH latest AS (
  SELECT DISTINCT ON (period, country, vendor) period, country, sell_in_mu
  FROM sales_team.smartwatch_market_data
  WHERE dataset = 'actual' AND LEFT(period, 4) IN ('2025', '2026')
  ORDER BY period, country, vendor, published_month DESC
), qs AS (
  SELECT DISTINCT RIGHT(period, 2) AS qn FROM latest WHERE LEFT(period, 4) = '2026'
), reg AS (
  SELECT LEFT(period, 4) AS yr, sell_in_mu,
         CASE
           WHEN country IN ('United States', 'USA', 'US', 'Canada') THEN '북미'
           WHEN country IN ('Germany', 'France', 'United Kingdom', 'UK', 'Italy', 'Spain', 'Netherlands', 'Sweden', 'Poland', 'Switzerland', 'Western Europe', 'Eastern Europe', 'Europe') THEN '유럽'
           WHEN country = 'China' THEN '중국'
           WHEN country IN ('Japan', 'South Korea', 'Korea', 'India', 'Taiwan', 'Indonesia', 'Vietnam', 'Thailand', 'Philippines', 'Malaysia', 'Australia', 'Asia Pacific', 'APAC') THEN '아시아(중국 제외)'
           ELSE '기타'
         END AS region
  FROM latest
  WHERE RIGHT(period, 2) IN (SELECT qn FROM qs)
)
SELECT region AS "지역",
       SUM(sell_in_mu) FILTER (WHERE yr = '2026') AS this_year_mu,
       SUM(sell_in_mu) FILTER (WHERE yr = '2025') AS last_year_mu,
       ROUND(100.0 * SUM(sell_in_mu) FILTER (WHERE yr = '2026')
             / SUM(SUM(sell_in_mu) FILTER (WHERE yr = '2026')) OVER (), 1) AS share_pct,
       ROUND(100.0 * (SUM(sell_in_mu) FILTER (WHERE yr = '2026') - SUM(sell_in_mu) FILTER (WHERE yr = '2025'))
             / NULLIF(SUM(sell_in_mu) FILTER (WHERE yr = '2025'), 0), 1) AS yoy_pct
FROM reg GROUP BY region ORDER BY this_year_mu DESC
```

### 그래프 색

그래프용 vendor 색 = Apple navy #0f1e3b, Samsung #2c57cd, Huawei #407aea, Garmin #87bafd, Fitbit #2342a3, Others #9aa8bd (`design/shadcn-navy-theme.css` 기준).

## 주의사항

- 테이블은 DBaaS 팀에 생성 요청 중이며, 생성 전에는 `schema` 명령이 테이블을 찾지 못한다.
