---
name: reports
kind: postgres
env: MI_DB_SMARTPHONE
tables: [sales_team.nasdaq_report_doc, sales_team.nasdaq_report_para]
summary: 증권사 레포트 (스마트폰 관련만, 요약·키워드·영문 본문, 문단별 티커·주제)
---
## 무엇이 들어 있나

- 스마트폰(완제품·부품·시장)과 관련된 증권사 레포트만 1건 = 1행으로 들어 있다. 원칙적으로 관련 없는 레포트는 없다 (분류 단계에서 제외된다).
- `body` 는 PDF에서 뽑은 **영어 원문**이다. 면책·공시 부분은 잘라냈고, 각 쪽 앞에 `[p.N]` 페이지 표시가 있다.
- `summary`, `keywords` 는 한국어와 영어가 함께 있다.
- `scope` 는 레포트의 티커, `topics` 는 7개 고정 주제(`ai, smartphone, auto, smartwatch, smartglass, tablet, humanoid`) 중 해당하는 것이다. 둘 다 사전으로 자동 집계한 값이다: 문단의 20% 이상 또는 제목에 나온 것. 티커 목록은 `tools/dict/tickers.csv`.
- `sales_team.nasdaq_report_para` 는 같은 본문을 문단 단위로 나눈 표다 (레포트 1건 = 문단 N행). 문단마다 그 안에 나온 티커·주제가 붙어 있다.

## 컬럼 의미

| column | 의미 | 비고 |
|---|---|---|
| id | 행 번호 | 2·3단계에서 레포트를 지정할 때 쓴다 |
| firm | 증권사 | 예: JPMorgan, Nomura |
| published_on | 발행일 | DATE |
| title | 제목 (영어) | |
| report_type | 종류 | weekly_note, company_update, industry_deep_dive, mgmt_meeting, firm_analysis, other, link_digest | `firm_analysis` 는 조사기관(예: TechInsights)의 해설 기사로 `minio_key` 가 `.md` 이고 `pages` 는 1이다. `link_digest`(링크 모음)는 보통 분류 단계에서 제외되지만 수동으로 들어올 수 있다 |
| topics | 주제, 쉼표로 이은 문자열 | ai, smartphone, auto, smartwatch, smartglass, tablet, humanoid 중에서 (자동 집계) |
| analyst | 애널리스트 | 없을 수 있음 |
| pages | PDF 전체 쪽수 | |
| minio_key | 원본 PDF의 MinIO 키 | `fetch minio <키>` 는 `MI_MINIO` 가 같은 버킷을 가리킬 때만 된다 |
| file_sha256 | PDF 지문 | 중복 방지용. 조회에 쓸 일 없음 |
| summary | 요약: 한국어 3~6줄 + 영어 1줄 | 한국어 1번째 줄은 주장, 2번째 줄부터는 `[p.N]` 이 붙은 근거. 훑어보기용이며 검색은 `body` 로 |
| keywords | 키워드: 한국어 + 영어, 쉼표로 이은 문자열 | |
| key_numbers | 핵심 숫자 메모 (자유 서술) | 출처 페이지 `[p.N]` 이 붙어 있을 수 있다 |
| thesis | 레포트의 주장 한 문장 (한국어) | "새 레포트 주장 목록" 을 뽑을 때 쓴다 |
| scope | 레포트의 티커, 쉼표로 이은 문자열 (예: `AAPL-USQ, 005930-KRX`) | 문단의 20% 이상 또는 제목에 나온 티커 (자동 집계). 한두 번 언급만 된 업체는 빠진다. 없으면 NULL |
| body | 본문 (영어 원문, `[p.N]` 표시) | 길다. 목록 조회에 넣지 않는다 |
| body_loaded | 본문 적재 여부 | 지금은 모두 true |
| loaded_at | 적재 시각 | |
| ticker | 티커 | 예: MU, AAPL. 산업 레포트는 비어 있음 |
| market | 거래소 코드 | 예: USQ |

## 문단 표 컬럼 (`sales_team.nasdaq_report_para`)

| column | 의미 | 비고 |
|---|---|---|
| id | 행 번호 | |
| doc_id | 레포트 행 번호 | `nasdaq_report_doc.id` 와 JOIN |
| page | 쪽 번호 | 답의 `[p.N]` 출처 |
| para_no | 레포트 안 문단 번호 | 1부터, 쪽을 넘어 이어짐 |
| tickers | 문단에 나온 티커, 쉼표로 이은 문자열 | 없으면 NULL |
| topics | 문단에 나온 주제, 쉼표로 이은 문자열 | 없으면 NULL |
| text | 문단 원문 (영어) | |

## 자주 쓰는 쿼리

```sql
-- 1) 메타로 좁히기: 한국어 단어 그대로 찾는다. body 는 가져오지 않는다.
SELECT id, firm, published_on, title, topics, summary
FROM sales_team.nasdaq_report_doc
WHERE published_on >= DATE '2026-07-01'
  AND topics LIKE '%smartphone%'
  AND (keywords ILIKE '%폴더블%' OR keywords ILIKE '%foldable%' OR summary ILIKE '%폴더블%')
ORDER BY published_on DESC;

-- 2) 좁힌 id 안에서 본문 위치 찾기: 본문은 영어라서 영어 단어로 찾는다 (폴더블 = foldable).
SELECT id, firm, published_on, title,
       substring(body FROM greatest(strpos(lower(body), 'foldable') - 300, 1) FOR 800) AS snippet
FROM sales_team.nasdaq_report_doc
WHERE id IN (3, 7, 12) AND body ILIKE '%foldable%';

-- 3) TechInsights 스마트워치 기사 최근 2건
SELECT id, published_on, title, summary, key_numbers
FROM sales_team.nasdaq_report_doc
WHERE firm = 'TechInsights' AND report_type = 'firm_analysis' AND topics LIKE '%smartwatch%'
ORDER BY published_on DESC LIMIT 2

-- 4) 한 건의 본문 전체 읽기
SELECT firm, published_on, title, body
FROM sales_team.nasdaq_report_doc WHERE id = 7;

-- 5) 이번 주 새 레포트: 주장과 자동 티커·주제
SELECT published_on, firm, thesis, scope, topics FROM sales_team.nasdaq_report_doc WHERE loaded_at >= CURRENT_DATE - 7 ORDER BY published_on DESC

-- 6) Apple 이 주제인 레포트 (Apple 이 한두 번 언급만 된 레포트는 제외)
SELECT id, published_on, firm, title, thesis FROM sales_team.nasdaq_report_doc WHERE scope LIKE '%AAPL-USQ%' ORDER BY published_on DESC

-- 7) 최근 14일 적재된 레포트에서 Apple 이 나온 문단
SELECT d.id, d.firm, d.published_on, d.title, p.page, p.text FROM sales_team.nasdaq_report_para p JOIN sales_team.nasdaq_report_doc d ON d.id = p.doc_id WHERE p.tickers LIKE '%AAPL-USQ%' AND d.loaded_at >= CURRENT_DATE - 14 ORDER BY d.published_on DESC, p.para_no

-- 8) 스마트워치 주제 문단 (최근 레포트부터)
SELECT d.id, d.firm, d.published_on, d.title, p.page, p.text FROM sales_team.nasdaq_report_para p JOIN sales_team.nasdaq_report_doc d ON d.id = p.doc_id WHERE p.topics LIKE '%smartwatch%' ORDER BY d.published_on DESC, p.para_no LIMIT 50
```

단어 문단 검색은 `WHERE body ILIKE '%foldable%'` 로 한다 (2번 쿼리). 찾은 문단 앞의 `[p.N]` 이 출처 쪽이다. 업체·주제로 문단을 찾을 때는 문단 표를 쓴다 (7·8번 쿼리, 출처 쪽은 `page`).
티커는 다른 티커 안에 들어 있을 수 있다 (`TM-USQ` 는 `STM-USQ` 안에도 있음). 정확히 찾을 때는 `', ' || scope || ', ' LIKE '%, TM-USQ, %'` 처럼 앞뒤에 쉼표를 붙인다.

## 주의사항

- 무엇이 있는지 먼저 볼 때: `SELECT firm, COUNT(*) AS n, MAX(published_on) AS latest FROM sales_team.nasdaq_report_doc GROUP BY firm ORDER BY n DESC`
- 답에는 근거마다 `(증권사, 발행일, 제목, [p.N])` 출처를 붙인다. 본문에 없는 내용은 지어내지 않고, 숫자는 본문 그대로 옮긴다.
- 문자열 안에 `update` 같은 단어를 따로 쓰면 SQL이 거부된다 (`report_type = 'company_update'` 는 괜찮다).
