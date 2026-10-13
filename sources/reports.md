---
name: reports
kind: postgres
env: MI_DB_SMARTPHONE
tables: [sales_team.nasdaq_report_doc]
summary: 증권사 레포트 (스마트폰 관련만, 요약·키워드·영문 본문)
---
## 무엇이 들어 있나

- 스마트폰(완제품·부품·시장)과 관련된 증권사 레포트만 1건 = 1행으로 들어 있다. 원칙적으로 관련 없는 레포트는 없다 (분류 단계에서 제외된다).
- `body` 는 PDF에서 뽑은 **영어 원문**이다. 면책·공시 부분은 잘라냈고, 각 쪽 앞에 `[p.N]` 페이지 표시가 있다.
- `summary`, `keywords` 는 한국어와 영어가 함께 있고, `topics` 는 한국어 고정 목록이다.

## 컬럼 의미

| column | 의미 | 비고 |
|---|---|---|
| id | 행 번호 | 2·3단계에서 레포트를 지정할 때 쓴다 |
| firm | 증권사 | 예: JPMorgan, Nomura |
| published_on | 발행일 | DATE |
| title | 제목 (영어) | |
| report_type | 종류 | weekly_note, company_update, industry_deep_dive, mgmt_meeting, other, link_digest | `link_digest`(링크 모음)는 보통 분류 단계에서 제외되지만 수동으로 들어올 수 있다 |
| topics | 주제, 쉼표로 이은 문자열 | 스마트폰, AP, 메모리, 카메라, 디스플레이, 모뎀, 파운드리, OEM, 공급망, 거시 중에서 |
| analyst | 애널리스트 | 없을 수 있음 |
| pages | PDF 전체 쪽수 | |
| minio_key | 원본 PDF의 MinIO 키 | `fetch minio <키>` 는 `MI_MINIO` 가 같은 버킷을 가리킬 때만 된다 |
| file_sha256 | PDF 지문 | 중복 방지용. 조회에 쓸 일 없음 |
| summary | 요약: 한국어 3줄 + 영어 1줄 | |
| keywords | 키워드: 한국어 + 영어, 쉼표로 이은 문자열 | |
| key_numbers | 핵심 숫자 메모 (자유 서술) | 출처 페이지 `[p.N]` 이 붙어 있을 수 있다 |
| body | 본문 (영어 원문, `[p.N]` 표시) | 길다. 목록 조회에 넣지 않는다 |
| body_loaded | 본문 적재 여부 | 지금은 모두 true |
| loaded_at | 적재 시각 | |
| ticker | 티커 | 예: MU, AAPL. 산업 레포트는 비어 있음 |
| market | 거래소 코드 | 예: USQ |

## 자주 쓰는 쿼리

```sql
-- 1) 메타로 좁히기: 한국어 단어 그대로 찾는다. body 는 가져오지 않는다.
SELECT id, firm, published_on, title, topics, summary
FROM sales_team.nasdaq_report_doc
WHERE published_on >= DATE '2026-07-01'
  AND topics ILIKE '%스마트폰%'
  AND (keywords ILIKE '%폴더블%' OR keywords ILIKE '%foldable%' OR summary ILIKE '%폴더블%')
ORDER BY published_on DESC;

-- 2) 좁힌 id 안에서 본문 위치 찾기: 본문은 영어라서 영어 단어로 찾는다 (폴더블 = foldable).
SELECT id, firm, published_on, title,
       substring(body FROM greatest(strpos(lower(body), 'foldable') - 300, 1) FOR 800) AS snippet
FROM sales_team.nasdaq_report_doc
WHERE id IN (3, 7, 12) AND body ILIKE '%foldable%';

-- 3) 한 건의 본문 전체 읽기
SELECT firm, published_on, title, body
FROM sales_team.nasdaq_report_doc WHERE id = 7;
```

## 주의사항

- 무엇이 있는지 먼저 볼 때: `SELECT firm, COUNT(*) AS n, MAX(published_on) AS latest FROM sales_team.nasdaq_report_doc GROUP BY firm ORDER BY n DESC`
- 답에는 근거마다 `(증권사, 발행일, 제목, [p.N])` 출처를 붙인다. 본문에 없는 내용은 지어내지 않고, 숫자는 본문 그대로 옮긴다.
- 문자열 안에 `update` 같은 단어를 따로 쓰면 SQL이 거부된다 (`report_type = 'company_update'` 는 괜찮다).
