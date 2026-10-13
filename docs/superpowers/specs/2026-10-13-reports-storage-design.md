# 증권사 레포트 저장 설계

작성일: 2026-10-13
상태: **설계 메모 (db_check 결과 대기 중)**

스마트폰 DB 정리가 먼저입니다. 이 문서는 그 뒤에 증권사 레포트 작업을 바로 시작할 수 있도록, 이미 합의된 결정과 db_check 결과로 정할 항목을 미리 적어둔 것입니다. 조사기관, 소스(`sources/*.md`), `query.py` 등 기존 결정은 [mi-sonar 설계 스펙](2026-10-13-mi-sonar-design.md)을 따르며 여기서 다시 쓰지 않습니다.

## 1. 결정 사항 (이미 합의된 것)

- **대상**: 스마트폰 관련 증권사 레포트만 본문을 적재합니다. 나머지는 원본 파일과 목록만 보관합니다.
- **범위**: 본문 + 요약까지. 표 안의 숫자(분기별 출하량 전망 등)를 구조화하는 일은 **다음 단계**입니다.
- **추정/가공 값은 저장하지 않음**: 기존 설계와 동일합니다.
- **쓰기 계정 분리**: 공유 읽기전용 계정과 별도의 쓰기 계정을 씁니다. 적재는 소유자(사용자)만 합니다.

## 2. 세 층 저장 구조

| 층 | 무엇 | 전부/선별 | 이유 |
|---|---|---|---|
| MinIO 원본 PDF | 레포트 PDF 파일 그대로 | 전부 | 비용이 거의 없고, 나중에 원본 요청에 대응 가능 |
| `report` 목록(메타데이터) | 증권사·발행일·제목·요약 등 | 전부 | 에이전트가 "무엇이 있는지" 알아야 함 |
| `chunk` 본문 조각 | PDF에서 뽑은 텍스트를 잘게 나눈 것 | 스마트폰 관련만 선별 | 적재 수고와 검색 노이즈(관련 없는 결과가 섞이는 것) 감소 |

`report.body_loaded` 플래그가 "본문까지 넣었는지"를 표시하므로, 나중에 본문만 추가로 넣을 수 있습니다.

## 3. 테이블 설계

먼저 용어 세 가지입니다.

- **기본키**: 행의 주민번호입니다. 절대 겹치지 않아서 같은 행이 중복 입력되는 것을 막습니다.
- **외래키**: 다른 테이블 행의 주민번호를 적어둔 칸입니다. 주인 없는 행(고아 행)을 막고, 주인 행을 지우면 딸린 행도 같이 지울 수 있습니다.
- **인덱스**: 책 뒤의 색인입니다. 자주 찾는 칸에만 만들며, 대가로 적재가 약간 느려집니다.

`{S}`는 자리표시자입니다. db_check 판정이 "스키마 분리 가능"이면 `{S}` = `reports.` 로 쓰고 맨 앞에 `CREATE SCHEMA reports;` 를 먼저 실행합니다. "테이블만 가능"이면 접두어 방식을 쓰며, 이때 두 테이블 이름은 `report_doc` 과 `report_chunk` 입니다. 즉 `{S}report` 는 `report_doc` 으로, `{S}chunk` 는 `report_chunk` 로 바뀌고, `{S}chunk` 의 외래키는 `report_doc(report_id)` 를 가리킵니다.

```sql
CREATE TABLE {S}report (
  report_id     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  firm          text        NOT NULL,            -- 증권사
  published_on  date        NOT NULL,            -- 발행일
  title         text        NOT NULL,
  report_type   text,                            -- 산업 / 기업 / 데일리 등
  topics        text[]      NOT NULL DEFAULT '{}',-- 예: {스마트폰, AP, 이미지센서}
  analyst       text,
  pages         int,
  minio_key     text        NOT NULL,            -- MinIO 경로
  file_sha256   text        NOT NULL UNIQUE,     -- 같은 PDF 두 번 넣기 차단
  summary       text,                            -- 에이전트가 쓴 3줄 요약
  keywords      text[]      NOT NULL DEFAULT '{}',-- 에이전트가 뽑은 키워드 ~10개
  key_numbers   text,                            -- 핵심 숫자 메모 (자유 서술; 구조화는 다음 단계)
  body_loaded   boolean     NOT NULL DEFAULT false,
  loaded_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON {S}report (firm, published_on);
CREATE INDEX ON {S}report (published_on);
CREATE INDEX ON {S}report USING gin (topics);
CREATE INDEX ON {S}report USING gin (keywords);

CREATE TABLE {S}chunk (
  chunk_id   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  report_id  bigint NOT NULL REFERENCES {S}report(report_id) ON DELETE CASCADE,
  page       int    NOT NULL,
  seq        int    NOT NULL,                     -- 같은 페이지 안 순서
  content    text   NOT NULL,
  UNIQUE (report_id, page, seq)
);
CREATE INDEX ON {S}chunk (report_id, page);
-- 본문 검색 인덱스는 db_check 결과에 따라 (6절)
-- 접두어 방식이면 {S}report -> report_doc, {S}chunk -> report_chunk, 외래키는 report_doc(report_id) 참조
```

각 키와 인덱스의 역할입니다.

| 항목 | 무엇 | 왜 |
|---|---|---|
| `report.report_id` (기본키) | 레포트 한 건의 번호 | 레포트를 하나로 특정 |
| `report.file_sha256` (UNIQUE) | PDF 파일의 지문 | 같은 PDF를 두 번 넣지 못하게 막음 |
| `chunk.chunk_id` (기본키) | 본문 조각 한 개의 번호 | 조각을 하나로 특정 |
| `chunk.report_id` (외래키) | 이 조각이 속한 레포트 번호 | 고아 조각 방지, 레포트 삭제 시 조각도 함께 삭제 |
| `chunk (report_id, page, seq)` (UNIQUE) | 레포트·페이지·순서 조합 | 같은 조각이 중복 적재되는 것을 막음 |
| 인덱스 `(firm, published_on)`, `(published_on)` | 증권사·기간 색인 | "A증권사 최근 3개월" 같은 조회를 빠르게 |
| 인덱스 `topics`, `keywords` (GIN) | 목록형 칸 안의 값을 찾는 색인 | "topics에 스마트폰 포함" 조회를 빠르게 |
| 인덱스 `chunk (report_id, page)` | 레포트·페이지 색인 | 좁힌 레포트의 앞뒤 페이지를 빠르게 읽기 |

## 4. 청크 규칙

청크란 긴 본문을 검색하기 좋게 잘라 둔 조각입니다.

- **단위**: 페이지 기준, 1000~1500자. 긴 페이지는 문단 경계에서 나누고 `seq` 를 1씩 늘립니다.
- **겹침 없음**: 페이지 단위라 앞뒤를 겹칠 필요가 없습니다.
- **표는 이번 단계에서 건너뜀**: 텍스트로 뽑으면 깨지기 때문입니다.
- **원칙**: 에이전트가 읽는 데는 비용이 들지 않으므로 "적당히 좁히고 많이 읽기"로 갑니다. 정밀 검색보다 조각 수를 적게 유지합니다.

## 5. 적재 흐름 (`tools/load_reports.py`, 나중에 제작)

1. PDF 선택 (스마트폰 관련만 본문 적재 대상)
2. MinIO 업로드 (키: `reports/{firm}/{published_on}_{제목slug}.pdf`)
3. 텍스트 추출 (pypdf)
4. 페이지 단위로 청크 나누기
5. **에이전트가 한 번 읽고** 요약 3줄, 키워드, 핵심 숫자 메모 작성
6. `report` 1행 + `chunk` N행을 한 트랜잭션(전부 성공하거나 전부 취소)으로 INSERT
7. 같은 해시(`file_sha256`)가 이미 있으면 건너뜀

쓰기 접속 문자열은 별도 환경변수 `MI_DB_REPORTS_WRITE` 에 두며, 소유자 PC에만 설정합니다.

## 6. 찾기(검색) 흐름 (에이전트 입장)

**1단계: `report` 메타로 좁히기** (증권사, 기간, topics, keywords)

```sql
SELECT report_id, firm, published_on, title, summary
FROM {S}report
WHERE published_on >= DATE '2026-01-01'
  AND topics @> ARRAY['스마트폰']
  AND keywords && ARRAY['폴더블']
ORDER BY published_on DESC;
```

**2단계: 좁힌 `report_id` 안에서 본문 찾기.** ILIKE는 대소문자를 구분하지 않고 글자가 포함됐는지 보는 단순 검색입니다. 찾은 페이지의 앞뒤 페이지도 같이 읽습니다.

```sql
SELECT report_id, page, seq, content
FROM {S}chunk
WHERE report_id IN (101, 102, 103)
  AND content ILIKE '%폴더블%'
ORDER BY report_id, page, seq;
```

답에는 항상 출처(증권사·발행일·제목·페이지)를 표기합니다.

업그레이드 경로입니다. db_check 7절·8절 결과로 결정합니다.

| 수단 | 필요 조건 | 효과 |
|---|---|---|
| ILIKE | 없음 (지금 바로 가능) | 글자가 그대로 들어 있는 곳을 찾음 |
| pg_trgm GIN | 확장(DB 추가 기능) 설치 가능 | 세 글자 단위로 색인해 오타·부분일치에 강하고 ILIKE도 빨라짐 |
| pgvector | 확장 + 임베딩(문장을 숫자로 바꾼 값) | 단어가 달라도 뜻이 비슷하면 찾는 의미 검색 |

## 7. 기존 `smartphone_market_data` 에도 적용할 후보

사용자 결정: 필요하면 기본키·외래키·인덱스를 적극 사용해도 됩니다. 아래는 후보이며, 테이블 소유권과 db_check 9절 프로필을 확인한 뒤 확정합니다.

1. **중복 차단**: (조사기관, 기간, 국가, 브랜드, 모델 …) 조합에 UNIQUE 인덱스를 만들어 같은 행이 두 번 적재되는 것을 막습니다.
2. **조회 인덱스**: 조사기관, 기간, 국가에 인덱스를 만듭니다. `query.py` 의 전형적인 WHERE 절이 이 칸들을 씁니다.
3. **조사기관 마스터 테이블 + 외래키**: 표기 흔들림(Counterpoint / counterpoint / CP)을 막습니다. `firm_narrative`(조사기관 내러티브)도 여기에 붙입니다.

주의: 이미 들어있는 데이터에 중복이 있으면 UNIQUE 생성이 실패합니다. 먼저 중복을 조회하고, 정리하고, 그다음 제약을 추가하는 순서로 진행합니다.

## 8. db_check 결과를 받으면 정할 것

- [ ] `{S}` 접두 방식: 스키마 분리(`reports.`) vs 테이블 접두어(`report_`)
- [ ] 본문 검색 인덱스: ILIKE만 / pg_trgm / pgvector
- [ ] 쓰기 계정 발급 여부
- [ ] `smartphone_market_data` 소유권 (제약을 추가할 수 있는지)
- [ ] 7절 후보 중 무엇을 적용할지

## 9. 다음 단계 순서

1. 스마트폰 DB 정리 (사내 작업 진행 중)
2. db_check 판정
3. 이 문서 8절 확정
4. `tools/load_reports.py` + `sources/reports.md` + SKILL.md 검색 단계 추가
5. 숫자 구조화 (별도 설계)
