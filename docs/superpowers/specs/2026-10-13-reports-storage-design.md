# 증권사 레포트 저장 설계

작성일: 2026-10-13
상태: **설계 확정 (2026-10-13) — 테이블 생성 대기, 로더 구현 중**

증권사 레포트(영문 PDF, 지금 약 54건) 중 스마트폰 관련만 골라 DB 테이블 1개에 넣고, 동료의 에이전트가 기존 `sql` 명령으로 찾아 읽게 하는 설계입니다. 조사기관, 소스(`sources/*.md`), `query.py` 등 기존 결정은 [mi-sonar 설계 스펙](2026-10-13-mi-sonar-design.md)을 따르며 여기서 다시 쓰지 않습니다. 구현 순서는 [load-reports 구현 계획](../plans/2026-10-13-load-reports.md)에 있습니다.

## 1. 결정 사항 (이미 합의된 것)

- **대상**: 스마트폰 관련 증권사 레포트만 적재합니다. 관련 없는 레포트는 DB에도 MinIO에도 올리지 않고, 내 PC의 `staging/triage.md` 에 "제외 + 이유"만 남깁니다. (2026-10-13 변경: 처음에는 나머지도 원본 파일과 목록을 보관하기로 했음)
- **범위**: 본문 + 요약까지. 표 안의 숫자(분기별 출하량 전망 등)를 구조화하는 일은 **다음 단계**입니다.
- **추정/가공 값은 저장하지 않음**: 기존 설계와 동일합니다.
- **쓰기 계정 분리**: 공유 읽기전용 계정과 별도의 쓰기 계정을 씁니다. 적재는 소유자(사용자)만 합니다.
- **역할 분담 (파이프라인 C)**: 기계적인 일은 프로그램이 하고, 판단은 에이전트가 합니다. 본문 텍스트는 프로그램만 만들며 에이전트는 절대 쓰지 않습니다.
- **로컬 먼저**: 회사 테이블이 생기기 전에는 내 PC의 내장 PostgreSQL에 먼저 쌓고, 테이블이 생기면 같은 작업 폴더를 그대로 회사 DB에 올립니다.

## 2. 저장 구조

| 위치 | 무엇 | 대상 | 누가 보나 |
|---|---|---|---|
| 회사 PostgreSQL `sales_team.nasdaq_report_doc` | 레포트 1건 = 1행: 메타·요약·키워드·핵심 숫자·본문 | 적재 대상만 | 동료 전원 (읽기전용 계정) |
| MinIO `reports/<증권사>/…pdf` | 원본 PDF | 적재 대상만 | 원본이 필요할 때 |
| 내 PC `staging/` | 추출 텍스트, 분류·주석 파일, `triage.md`, 로컬 DB | 전부 | 소유자 PC에서만 (밖으로 나가지 않음, git에서 제외) |

테이블을 하나로 한 이유입니다.

- 수십 건 규모라 본문 조각(청크) 테이블이 필요 없습니다. 본문 한 칸(`body`)에 페이지 표시 `[p.N]` 을 넣어 두면 출처 페이지를 그대로 인용할 수 있습니다.
- 에이전트는 좁힌 레포트의 본문을 통째로 읽고 답합니다. 읽는 데는 비용이 거의 들지 않으므로 "적당히 좁히고 많이 읽기"로 갑니다.
- 외래키·조인이 없어 DBaaS 팀 요청이 테이블 1개로 끝나고, 동료의 쿼리도 단순합니다.
- 새 스키마를 요청하지 않고 기존 `sales_team` 스키마에 둡니다.

## 3. 테이블 설계

먼저 용어입니다 (7절에서도 씁니다).

- **기본키**: 행의 주민번호입니다. 절대 겹치지 않아서 같은 행이 중복 입력되는 것을 막습니다.
- **외래키**: 다른 테이블 행의 주민번호를 적어둔 칸입니다. 주인 없는 행(고아 행)을 막습니다. 이 테이블에는 없습니다.
- **UNIQUE**: 이 칸에는 같은 값이 두 번 들어갈 수 없다는 약속입니다. 같은 PDF가 두 번 적재되는 것을 DB가 막아 줍니다.
- **인덱스**: 책 뒤의 색인입니다. 자주 찾는 칸에만 만들며, 대가로 적재가 약간 느려집니다.

```sql
CREATE TABLE sales_team.nasdaq_report_doc (
  id SERIAL PRIMARY KEY,
  firm VARCHAR(100) NOT NULL,
  published_on DATE NOT NULL,
  title VARCHAR(300) NOT NULL,
  report_type VARCHAR(50),
  topics VARCHAR(300),
  analyst VARCHAR(100),
  pages INTEGER,
  minio_key VARCHAR(500) NOT NULL,
  file_sha256 VARCHAR(64) NOT NULL UNIQUE,
  summary TEXT,
  keywords VARCHAR(500),
  key_numbers TEXT,
  body TEXT,
  body_loaded BOOLEAN NOT NULL DEFAULT FALSE,
  loaded_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  ticker VARCHAR(20),
  market VARCHAR(10)
);
```

| 칸 | 의미 | 채우는 곳 |
|---|---|---|
| `id` | 행 번호 (기본키, 자동 증가) | DB |
| `firm` | 증권사 (예: JPMorgan) | 파일명 |
| `published_on` | 발행일 | 파일명 |
| `title` | 제목 (영어) | 파일명. 없거나 잘렸으면 에이전트가 1쪽에서 |
| `report_type` | 레포트 종류 (분류의 `kind`) | 에이전트 |
| `topics` | 주제. 고정 목록(5절)에서 고른 값을 쉼표로 이은 문자열 | 에이전트 |
| `analyst` | 대표 애널리스트 (보이면) | 에이전트 |
| `pages` | PDF 전체 쪽수 | 프로그램 |
| `minio_key` | 원본 PDF 위치 `reports/<증권사>/<발행일>_<slug>.pdf` | 프로그램 |
| `file_sha256` | PDF 지문 (UNIQUE: 같은 PDF 두 번 적재 차단) | 프로그램 |
| `summary` | 한국어 3줄 + 영어 1줄 (줄바꿈으로 구분) | 에이전트 |
| `keywords` | 한국어 10개 이하 + 영어 10개 이하를 쉼표로 이은 문자열 | 에이전트 |
| `key_numbers` | 핵심 숫자 메모 (자유 서술, 구조화는 다음 단계) | 에이전트 |
| `body` | 정리된 본문 (영어 원문, `[p.N]` 페이지 표시, 4절) | 프로그램 |
| `body_loaded` | 본문을 넣었는지. 지금은 적재하는 행 모두 TRUE | 프로그램 |
| `loaded_at` | 적재 시각 | DB |
| `ticker` | 티커 (예: MU). 산업 레포트는 비어 있음 | 파일명, 없으면 에이전트 |
| `market` | 거래소 코드 (예: USQ) | 파일명 |

- `topics`, `keywords` 는 목록(배열)이 아니라 `메모리, 스마트폰` 같은 쉼표로 이은 문자열입니다. 찾을 때는 `ILIKE '%메모리%'` 를 씁니다.
- `slug` 는 제목의 영문·숫자를 `_` 로 이은 앞 60자 + PDF 지문 앞 6자리입니다 (예: `reports/JPMorgan/2026-10-06_Micron_Technology_Mgmt_Mtg_a1b2c3.pdf`). 지문을 붙여 같은 날 같은 제목의 두 레포트가 서로 덮어쓰지 않게 합니다.
- **인덱스는 지금 요청하지 않습니다.** 수십 건이라 순차 검색(ILIKE)으로 충분합니다. 서버에 pg_trgm(부분일치 색인)과 pgvector(의미 검색)가 이미 있으므로, 건수가 늘어 느려지면 그때 요청합니다.

## 4. 본문 정리 규칙

PDF에서 뽑은 글자를 읽기 좋은 본문으로 만드는 규칙입니다. 프로그램(`extract`)이 모든 레포트에 똑같이 적용합니다. 근거는 사내 추출 점검(54건, 중앙값 13쪽) 결과입니다.

1. **면책·공시 꼬리 자르기**: 2쪽부터 보아, `Analyst Certification` 또는 `Important Disclosures` 로 시작하는 줄이 처음 나오는 곳(둘 중 먼저 나오는 것)부터 끝까지 버립니다. 그 쪽에서 제목 앞에 있는 글은 남깁니다. 1쪽은 "공시는 몇 쪽 참조" 같은 문구가 흔해서 보지 않습니다. 이 꼬리는 보통 전체 쪽수의 35~60%입니다.
2. **반복되는 머리말·꼬리말 지우기**: 전체 쪽의 60% 이상에 똑같이 나오는 줄(예: `Nomura | Largan Precision 8 October 2026`)을 모든 쪽에서 지웁니다. 꼬리를 자르기 전에 전체 쪽을 기준으로 셉니다. 3쪽 미만 문서는 건너뜁니다.
3. **쪽 번호 줄 지우기**: 숫자만 있는 줄을 지웁니다.
4. **줄바꿈 이어 붙이기**: PDF는 문장 중간에서 줄을 바꾸고, 문단 사이에 빈 줄이 없습니다. 줄을 공백으로 이어 붙이되, `.` `:` `?` `!` 로 끝나는 줄 뒤와 글머리표(•, -, 1. 등) 줄 앞에서 문단을 나눕니다. `-` 로 끝나는 줄은 공백 없이 붙입니다 (`high-` + `end` → `high-end`). 결과는 문단 하나가 한 줄입니다.
5. **특수문자 정리**: 합자(ﬁ → fi), 줄바꿈 없는 공백 같은 글자를 보통 글자로 바꿉니다.
6. **페이지 표시**: 각 쪽 본문 앞에 `[p.N]` 한 줄을 넣습니다. N은 PDF의 실제 쪽 번호라 답에서 그대로 인용할 수 있습니다. 내용이 없는 쪽은 표시도 생략합니다.
7. **표는 그대로 둡니다**: 넓은 표는 한 줄(약 450자)로 나오지만 줄 단위로 읽을 수 있으므로 버리지 않습니다. 두 단 섞임은 점검에서 발견되지 않았습니다.

정리 결과는 `staging/<id>/text.txt` 에 저장되고, 그대로 `body` 칸에 들어갑니다. 자르기 결과(남은 쪽 수, 자른 제목)는 `meta.json` 과 추출 로그에 남아 잘못 잘린 레포트를 골라낼 수 있습니다.

## 5. 적재 흐름 (네 단계, `tools/load_reports.py`)

| 단계 | 누가 | 무엇 | 결과물 |
|---|---|---|---|
| 1. `extract` | 프로그램 | 파일명 해석, PDF 지문(sha256), 텍스트 추출(pymupdf, 없으면 pdfplumber, 그다음 pypdf), 4절 정리, 참고 신호 계산(스마트폰 단어 수, URL 수) | `staging/<id>/text.txt`, `meta.json` |
| 2. triage (분류) | 에이전트 | `text.txt` 전체를 읽고 종류·관련도·이유를 기록 | `staging/<id>/triage.json` |
| | 프로그램 | 결정 규칙 적용, 사용자 검토용 표 작성 (`triage-report`) | `staging/triage.md` |
| 3. annotate (주석) | 에이전트 | 적재 대상만: 제목·요약·키워드·주제·핵심 숫자 등을 기록 | `staging/<id>/annotate.json` |
| 4. `load` | 프로그램 | 검증 → (MinIO 업로드) → 1행 INSERT. 레포트마다 한 트랜잭션 | DB 행, MinIO 객체 |

`status` 명령은 레포트마다 한 줄로 단계 상태(분류·결정·주석·적재)와 파일 오류를 보여줍니다. 이 로더는 소유자만 쓰므로 PDF 라이브러리는 개발용 의존성(`requirements-dev.txt`)에만 넣고, 동료 설치(`install.ps1`)는 바뀌지 않습니다.

### 작업 폴더 (`staging/`)

- `staging/<id>/` 폴더 하나가 레포트 하나입니다. `id` 는 PDF 지문(sha256)의 앞 12자리라서, 파일 이름이 달라도 같은 PDF면 같은 폴더입니다.
- `text.txt`, `meta.json` 은 프로그램만 씁니다. `triage.json`, `annotate.json` 은 에이전트만 씁니다 (사용자는 `triage.json` 에 `load` 만 추가할 수 있음).
- 원본 PDF는 복사하지 않고 경로만 `meta.json` 에 적습니다.
- `staging/` 은 git에서 제외되며 PC 밖으로 나가지 않습니다.

### 파일명 해석

형식은 `DD-Mon-YYYY_HH-MM-SS-<TICKER>-<MARKET>-<FIRM>-<TITLE>.pdf` 이고 확장자는 `.PDF` 처럼 대문자일 수 있습니다. 54건 중 35건이 완전한 형태이며, 나머지 세 모양도 처리합니다.

| 모양 | 예 | 처리 |
|---|---|---|
| 완전 (35건) | `06-Oct-2026_08-02-29-MU-USQ-JPMorgan-Micron_Technology_Mgmt_Mtg__CY27_and_CY28_Both_Significantly_Ti.pdf` | 티커 MU, 시장 USQ, 증권사 JPMorgan, 제목은 `_` 를 공백으로 |
| 제목 없음 (11건) | `…-AAPL-USQ-Jefferies.PDF` | 제목은 에이전트가 1쪽에서 채움 |
| 증권사만 (5건) | `…-JPMorgan.PDF` | 제목·티커는 에이전트가 채움 |
| 티커·시장 없음 (3건) | `…-Nomura-Largan_Precision_….pdf` | 단일 기업 레포트면 에이전트가 티커를 채움 |

파일명의 제목은 중간에 잘린 경우가 많아서, 에이전트가 1쪽의 전체 제목으로 바꿔 쓸 수 있습니다. 해석이 틀린 파일은 이름을 위 형식으로 고친 뒤 `extract --force` 로 다시 추출합니다.

### 분류 (triage) 기준: 관문

에이전트가 `text.txt` 전체를 읽고 기록합니다. 스마트폰 단어는 54건 중 51건에 한 번 이상 나오므로, 단어 수는 참고 신호일 뿐 결정 근거가 아닙니다.

- `kind` (종류)
  - `link_digest`: 다른 레포트·뉴스 링크와 제목을 모아 놓은 것 (자체 분석이 거의 없음)
  - `weekly_note`: 여러 항목을 다루는 주간(정기) 노트
  - `company_update`: 한 기업에 대한 실적 전망·리뷰, 추정치·투자의견 변경, 뉴스 반응
  - `industry_deep_dive`: 산업·테마 심층 분석 (시장 규모, 공급망, 전망)
  - `mgmt_meeting`: 경영진 미팅, 투자자의 날, 컨퍼런스 미팅, 현장 방문 정리
  - `firm_analysis`: 조사기관(예: TechInsights)이 발행하는 짧은 해설 기사. PDF 가 아니라 소유자가 붙여넣은 텍스트(`.md`)로 들어온다
  - `other`: 그 밖의 것
- `relevance` (관련도)
  - `high`: 스마트폰·휴대폰·휴대폰 부품 **또는 스마트워치**의 시장, 출하량, 제조사(OEM)가 **주제**인 레포트
  - `medium`: 주제는 다르지만 스마트폰·휴대폰·휴대폰 부품 **또는 스마트워치** 수요를 다루는 부분이 있는 레포트 (예: 모바일 수요 단락이 있는 메모리 레포트)
  - `low`: 무관
- `reason`: 왜 그렇게 봤는지 한 줄 (한국어)

**결정 규칙 (프로그램)**: `relevance` 가 high 또는 medium 이고 `kind` 가 `link_digest` 가 아니면 적재합니다. 사용자는 `triage.md` 를 보고 해당 `triage.json` 에 `"load": true` 또는 `"load": false` 를 넣어 결정을 뒤집을 수 있으며, 이 값이 규칙보다 우선합니다. 제외된 레포트는 DB에도 MinIO에도 올라가지 않고 `triage.md` 에만 "제외 + 이유"로 남습니다.

### 주석 (annotate) 항목: 적재 대상만

| 항목 | 내용 | 저장 칸 |
|---|---|---|
| `title` | 파일명에 제목이 없으면 필수. 잘렸으면 1쪽의 전체 제목으로 | `title` |
| `ticker` | 파일명에 없고 단일 기업 레포트일 때 | `ticker` |
| `analyst` | 이름이 보이면 대표 애널리스트 | `analyst` |
| `thesis` | 필수. 레포트의 주장 한 문장 (한국어, 10~300자, 한 줄) | `thesis` |
| `scope` | 필수. 레포트가 무엇에 대한 것인지 1~6개: `market`(시장 전반), `vendor:<업체명>`(특정 업체가 주제, 업체명에 쉼표 없음), `band:<high\|mid\|low>`(특정 가격대). 여러 개 가능 | `scope` = 쉼표로 이음 (예: `market, vendor:Apple`) |
| `summary_ko` | 한국어 요약 3~6줄 (한 줄에 한 문장). 1번째 줄은 `thesis` 를 다시 쓰거나 핵심 주장, 2번째 줄부터는 근거이며 각 줄에 `[p.N]` 포함 | `summary` = 한국어 줄들 + 줄바꿈 + 영어 1줄 |
| `summary_en` | 영어 요약 1줄 | (위와 같이 `summary` 에) |
| `keywords_ko`, `keywords_en` | 각 10개 이하, 키워드 안에 쉼표 없음 | `keywords` = 한국어 + 영어를 쉼표로 이음 |
| `topics` | 고정 목록에서 1개 이상: 스마트폰, AP, 메모리, 카메라, 디스플레이, 모뎀, 파운드리, OEM, 공급망, 거시, 스마트워치 | `topics` (쉼표로 이음) |
| `key_numbers` | 핵심 숫자를 단위·기간과 함께 그대로, 출처 `[p.N]` 포함. 없으면 빈 문자열 | `key_numbers` |
| (분류의 `kind`) | | `report_type` |

요약은 검색용이 아니라 훑어보기용입니다 (본문은 전문 저장되어 ILIKE/pg_trgm 로 문단 검색이 가능합니다). `thesis` 로 "이번 주 새 레포트들의 주장 목록" 을 한 쿼리로 뽑습니다. `scope` 는 TAM 점검용입니다: Apple 이 언급된 레포트가 아니라 Apple 이 주제인 레포트를 찾습니다.

`firm_analysis` 기사는 추가 규칙이 있다: `keywords_en` 에 기사에 나온 모든 업체명과 모든 국가·지역명을 넣고(예: `Apple, Huawei, China, India`), `keywords_ko` 에 그 한국어 표기를 넣는다. `key_numbers` 에는 출하량·성장률 숫자를 모두 원문 그대로 `[p.1]` 과 함께 옮긴다. 기사는 1쪽짜리 텍스트라 면책 절단·머리말 제거를 하지 않는다.

에이전트는 `text.txt` 전체를 읽은 뒤 쓰고, 레포트에 있는 내용만 씁니다. 요약은 본문을 대신하지 않으며 본문은 프로그램이 만든 그대로 저장됩니다.

### 적재 (`load`)

- `load --local`: 내 PC의 내장 PostgreSQL(`pgserver`, 데이터는 `staging/localpg/`)에 `sales_team` 스키마와 3절 테이블을 없으면 만들고 적재합니다. MinIO는 쓰지 않습니다.
- `load --dsn-env MI_DB_REPORTS_WRITE`: 같은 작업 폴더를 회사 DB에 적재하고 원본 PDF를 MinIO(`MI_MINIO_WRITE`)에 올립니다. 회사 DB에는 아무것도 만들지 않으며, 테이블이 없으면 멈춥니다. `--no-minio` 를 주면 업로드만 건너뜁니다.
- 같은 지문(`file_sha256`)이 이미 있으면 건너뜁니다 (MinIO 업로드도 하지 않음). 몇 번을 다시 돌려도 결과가 같습니다.
- 레포트 하나 = 한 트랜잭션입니다. 한 건이 실패해도 나머지는 계속하고, 마지막에 건수를 보여줍니다.
- `minio_key` 는 `--no-minio` 여도 항상 계산해서 저장합니다.
- 쓰기 접속 정보는 환경변수 `MI_DB_REPORTS_WRITE`(DB 접속 문자열)와 `MI_MINIO_WRITE`(MinIO, `MI_MINIO` 와 같은 형식)에만 두고, 소유자 PC의 현재 터미널에서만 설정합니다. 화면·파일·오류 메시지에 절대 출력하지 않습니다.

## 6. 찾기(검색) 흐름 (동료 에이전트 입장)

동료는 다시 설치할 필요가 없습니다. 같은 DB의 읽기전용 계정(`MI_DB_SMARTPHONE`)을 쓰는 새 소스 설명 파일 `sources/reports.md`(kind postgres, 테이블 `sales_team.nasdaq_report_doc`)만 추가되며, 기존 `sql` 명령으로 조회합니다. SKILL.md에는 "증권사 레포트 찾기" 단계가 짧게 추가됩니다.

**1단계: 메타로 좁히기.** 한국어 요약·키워드·주제가 있으므로 질문의 한국어 단어로 바로 찾고, 증권사·기간으로 거릅니다. 이 단계에서는 `body` 를 가져오지 않습니다.

```sql
SELECT id, firm, published_on, title, topics, summary
FROM sales_team.nasdaq_report_doc
WHERE published_on >= DATE '2026-07-01'
  AND topics ILIKE '%스마트폰%'
  AND (keywords ILIKE '%폴더블%' OR keywords ILIKE '%foldable%' OR summary ILIKE '%폴더블%')
ORDER BY published_on DESC;
```

**2단계: 본문에서 위치 찾기.** 본문은 영어 원문이므로 질문 단어를 영어로 바꿔(폴더블 → foldable) 좁힌 `id` 안에서 `body ILIKE` 로 찾고, 그 주변만 잘라 봅니다. ILIKE는 대소문자를 구분하지 않고 글자가 포함됐는지 보는 단순 검색입니다.

```sql
SELECT id, firm, published_on, title,
       substring(body FROM greatest(strpos(lower(body), 'foldable') - 300, 1) FOR 800) AS snippet
FROM sales_team.nasdaq_report_doc
WHERE id IN (3, 7, 12) AND body ILIKE '%foldable%';
```

**3단계: 읽고 답하기.** 필요한 레포트의 `body` 를 한 건씩 가져와 끝까지 읽고 한국어로 답합니다. 본문에 없는 내용은 지어내지 않습니다.

```sql
SELECT firm, published_on, title, body FROM sales_team.nasdaq_report_doc WHERE id = 7;
```

답에는 근거마다 출처(증권사·발행일·제목·`[p.N]`)를 붙입니다. `[p.N]` 은 본문 속 페이지 표시를 그대로 옮깁니다.

업그레이드 경로입니다 (지금은 ILIKE만 씀).

| 수단 | 필요 조건 | 효과 |
|---|---|---|
| ILIKE | 없음 (지금 바로 가능) | 글자가 그대로 들어 있는 곳을 찾음 |
| pg_trgm GIN 인덱스 | 확장은 서버에 있음, 인덱스 생성 요청 필요 | 건수가 늘어 ILIKE가 느려지면 빠르게 함 |
| pgvector | 확장은 서버에 있음, 임베딩(문장을 숫자로 바꾼 값) 생성 필요 | 단어가 달라도 뜻이 비슷하면 찾는 의미 검색 |

## 7. 기존 `smartphone_market_data` 에도 적용할 후보

사용자 결정: 필요하면 기본키·외래키·인덱스를 적극 사용해도 됩니다. 아래는 후보이며, 테이블 소유권과 db_check 9절 프로필을 확인한 뒤 확정합니다.

1. **중복 차단**: (조사기관, 기간, 국가, 브랜드, 모델 …) 조합에 UNIQUE 인덱스를 만들어 같은 행이 두 번 적재되는 것을 막습니다.
2. **조회 인덱스**: 조사기관, 기간, 국가에 인덱스를 만듭니다. `query.py` 의 전형적인 WHERE 절이 이 칸들을 씁니다.
3. **조사기관 마스터 테이블 + 외래키**: 표기 흔들림(Counterpoint / counterpoint / CP)을 막습니다. `firm_narrative`(조사기관 내러티브)도 여기에 붙입니다.

주의: 이미 들어있는 데이터에 중복이 있으면 UNIQUE 생성이 실패합니다. 먼저 중복을 조회하고, 정리하고, 그다음 제약을 추가하는 순서로 진행합니다.

## 8. 남은 확인 사항

- [x] 저장 구조 → 단일 테이블 `sales_team.nasdaq_report_doc` (기존 스키마, 새 스키마 요청 안 함)
- [x] 본문 검색 → ILIKE로 시작, 인덱스는 나중 (pg_trgm·pgvector는 서버에 있음)
- [x] 쓰기 계정 발급 여부 → 있음 (`MI_DB_REPORTS_WRITE`)
- [ ] DBaaS 팀 테이블 생성 결과 (8b 요청문)
- [ ] 권한 (별도 요청): 쓰기 계정은 이 테이블 SELECT·INSERT와 자동 번호 시퀀스(`sales_team.nasdaq_report_doc_id_seq`) USAGE가 필요합니다. 읽기 계정(`MI_DB_SMARTPHONE`)은 이 테이블 SELECT가 필요합니다.
- [ ] MinIO: 레포트 원본을 올릴 버킷과 쓰기 키(`MI_MINIO_WRITE`), 동료의 읽기 키(`MI_MINIO`)로 그 버킷을 받을 수 있는지
- [ ] `smartphone_market_data` 소유권 (제약을 추가할 수 있는지)
- [ ] 7절 후보 중 무엇을 적용할지

## 8b. DBaaS 팀 요청문

```
[요청] sales_team 스키마에 테이블 1개 생성
1. 테이블 이름: sales_team.nasdaq_report_doc
2. DDL:
CREATE TABLE sales_team.nasdaq_report_doc (
  id SERIAL PRIMARY KEY,
  firm VARCHAR(100) NOT NULL,
  published_on DATE NOT NULL,
  title VARCHAR(300) NOT NULL,
  report_type VARCHAR(50),
  topics VARCHAR(300),
  analyst VARCHAR(100),
  pages INTEGER,
  minio_key VARCHAR(500) NOT NULL,
  file_sha256 VARCHAR(64) NOT NULL UNIQUE,
  summary TEXT,
  keywords VARCHAR(500),
  key_numbers TEXT,
  body TEXT,
  body_loaded BOOLEAN NOT NULL DEFAULT FALSE,
  loaded_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  ticker VARCHAR(20),
  market VARCHAR(10)
);
3. 인덱스: 지금은 요청하지 않음 (수십 건 규모). 확장 pg_trgm, vector 는 이미 설치되어 있어 추가 요청 없음
용도: 증권사 레포트 요약·본문 저장 (수십 건, 수 MB 수준). 기존 sales_team 테이블은 건드리지 않음.
```

권한(쓰기 계정과 읽기 계정이 이 테이블에 무엇을 할 수 있는지)은 이 요청과 별도로 요청합니다. 필요한 내용은 8절에 있습니다.

## 9. 다음 단계 순서

1. 스마트폰 DB 정리 (사내 작업 진행 중)
2. db_check 판정 (완료)
3. 레포트 추출 점검 (완료: 파일명 모양, 공시 꼬리, 머리말·꼬리말, 줄바꿈, 표 확인)
4. DBaaS 팀 테이블 생성 요청 (8b) + 권한 별도 요청: 대기 중
5. `tools/load_reports.py` 구현 → 사내 에이전트가 extract·triage·annotate 후 `load --local` 로 로컬에 쌓기
6. 테이블과 권한이 생기면 `load --dsn-env MI_DB_REPORTS_WRITE` 로 회사 DB와 MinIO에 적재하고, `sources/reports.md` + SKILL.md 검색 단계 배포
7. 숫자 구조화 (별도 설계)
