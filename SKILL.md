---
name: mi-sonar
description: 스마트폰 시장 데이터(smartphone_market_data) 조회·집계·추세 분석과 MinIO 원본 파일 다운로드, 증권사 레포트(브로커 리서치) 검색·요약. "출하량", "점유율", "판매량", "성장률", "YoY", "모델별/분기별 수치", "제조사", "브랜드", "모델", "갤럭시", "아이폰", "분기", "조사기관", "market share", "shipments", "시장 데이터", "원본 파일", "mi-sonar 설치 확인", "증권사 레포트", "리포트", "애널리스트", "broker report" 같은 요청에 사용. 모든 DB 접근은 scripts/query.py 로만 한다.
---

# mi-sonar

읽기전용 데이터 조회 스킬. 실행 파일은 `scripts/query.py` 하나뿐이다.
아래 명령은 Git Bash와 PowerShell 모두에서 그대로 동작한다:

| 목적 | 명령 |
|---|---|
| 소스 목록·환경변수 상태 | `python "$HOME/.claude/skills/mi-sonar/scripts/query.py" sources` |
| 테이블 컬럼·샘플 | `python "$HOME/.claude/skills/mi-sonar/scripts/query.py" schema smartphone` |
| SQL 실행 | `python "$HOME/.claude/skills/mi-sonar/scripts/query.py" sql smartphone "SELECT ..." [--limit N] [--csv 파일]` |
| 원본 목록 | `python "$HOME/.claude/skills/mi-sonar/scripts/query.py" ls minio [접두어]` |
| 원본 다운로드 | `python "$HOME/.claude/skills/mi-sonar/scripts/query.py" fetch minio <키> [--out 경로]` |

SQL은 큰따옴표로 감싸고, SQL 안의 문자열 리터럴은 작은따옴표로 쓴다. SQL 안에는 `$` 를 절대 쓰지 않는다.

## 작업 순서

1. **설치 확인**: 세션에서 처음 쓸 때 `sources` 실행. 질문에 필요한 소스가 `미설정`일 때만 사용자에게
   "README 맨 위의 설치 한 줄을 PowerShell에 붙여넣고 새 터미널을 여세요"라고 안내하고 중단.
   DB 질문은 `smartphone` 만 있으면 된다 (`minio` 는 원본 파일이 필요할 때만). 환경변수 값은 절대 출력하지 않는다.
2. **소스 이해**: `sources/smartphone.md`의 컬럼 의미를 읽는다. 세션당 1회 `schema smartphone`으로
   실제 컬럼을 확인한다(컬럼은 바뀔 수 있다. 문서가 아니라 `schema` 출력이 정답).
3. **조사기관 확정**: 이 테이블은 같은 항목을 여러 조사기관이 전망한 행이 함께 들어 있다.
   - 사용자가 기관을 지정했으면 그 기관으로 필터한다.
   - 지정하지 않았으면 먼저 질문 조건으로 기관별 커버리지를 확인한다:
     `SELECT <기관컬럼>, COUNT(*) AS n, MIN(<기간컬럼>) AS first, MAX(<기간컬럼>) AS last FROM smartphone_market_data WHERE <질문 조건> GROUP BY 1 ORDER BY n DESC`
     그 결과를 근거로 가장 적합한 기관 1개(커버리지 넓고 최신)를 제안하고, "X 기관 기준으로 볼까요? (다른 선택지: Y, Z)" 라고 **사용자에게 확인을 받은 뒤** 집계한다.
   - 기관 간 합산은 절대 하지 않는다. 비교 요청이면 기관을 열로 펼친다.
   - 답변에 항상 어느 기관 기준인지 명시한다.
4. **기관 혼합 (추정)**: 기준 기관에 없는 항목(예: 특정 국가·모델)을 다른 데이터로 보완해야 할 때만 쓴다.
   - 원칙 1: 숫자는 **같은 기관 안에서만** 더하고 뺀다. 다른 기관의 숫자는 **비율로만** 쓴다.
   - 원칙 2: 추정값은 DB에 저장하지 않는다. 질문마다 SQL 집계 결과를 pandas로 계산한다.
   - 같은 기관, 다른 주기: 세분 주기(예: weekly)의 값을 큰 주기(예: monthly)로 합산해, 큰 주기의 상위 묶음(예: Others)에서 빼서 분리한다.
     예) monthly에 일본이 없고 weekly에 있으면: 일본(월) = Σ weekly 일본, Others(월, 조정) = Others(월) − 일본(월).
     주가 월 경계를 걸치면 일수 비례로 나누고, 그 사실을 계획에 적는다.
   - 다른 기관: 타 기관에서 비율 = 대상 ÷ 분모 를 구해 기준 기관의 같은 분모 값에 곱한다.
     분모는 가능하면 대상이 포함된 같은 범위의 상위 묶음(예: 일본이 들어 있는 Others 또는 Asia), 그게 없으면 전체 합계. 어느 분모를 썼는지 계획에 적는다.
     예) 일본이 기관 B에만 있으면: 일본(A, 추정) = Others(A) × [일본(B) ÷ Others(B)].
   - **혼합 계획을 먼저 보여주고 사용자 확인을 받은 뒤 계산한다.** 계획 양식:
     `기준 기관: A / 부족한 항목: 일본 월별 / 보완: B의 비율 (분모 Others) / 식: Others(A)×일본(B)/Others(B) / 기간: 2026-01~06`
   - 답변 표에서 추정 셀은 `(추정)` 을 붙이고, 표 아래에 계산식과 사용한 기관·분모를 적는다.
5. **집계는 DB에서**: 모델/기간/지역별 수치, 점유율, YoY는 SQL `GROUP BY`로 계산해 작은 결과만 가져온다.
   원시 행을 통째로 가져오지 않는다. "잘렸습니다" 안내가 나오면 더 집계하거나 `--limit` 을 올린다.
   `--csv` 도 같은 행 제한(최대 5,000행)이 걸리므로 잘림을 피하는 방법이 아니다.
6. **가공**: 표는 그대로 보여준다. 추세·차트·요약은 먼저 SQL로 집계하고, 5,000행 이하의 집계 결과만
   `--csv`로 저장해 pandas/matplotlib로 처리한다.
   - pandas/matplotlib가 없으면 사용자에게 알리고 `python -m pip install pandas matplotlib` 를 실행한다.
   - 그리기 전에 `plt.rcParams['font.family']='Malgun Gothic'`, `plt.rcParams['axes.unicode_minus']=False` 를 설정한다.
7. **원본 파일**: 행의 원본 키 컬럼 값으로 `fetch minio <키>`. 위치를 모르면 `ls minio <접두어>`.
8. **답변에 SQL 포함**: 사용한 SQL을 코드블록으로 같이 보여준다(동료가 재현·검증 가능).

## 증권사 레포트 찾기 (소스 `reports`)

스마트폰 관련 증권사 레포트 1건 = 1행 (`sales_team.nasdaq_report_doc`). 컬럼과 예시 쿼리는 `sources/reports.md`.

1. **좁히기**: `topics`, `keywords`, `summary`, `title` 을 질문의 한국어·영어 단어로 `ILIKE` 하고 증권사·기간으로 거른다. 이 단계에서는 `body` 를 SELECT 하지 않는다.
2. **본문 위치**: 좁힌 `id` 안에서 `body ILIKE '%영어 단어%'`. 본문은 영어 원문이므로 질문 단어를 영어로 바꿔 찾는다.
3. **읽기**: 필요한 레포트의 `body` 를 한 건씩 가져와 끝까지 읽고 한국어로 답한다. 본문에 없는 내용은 지어내지 않는다.
4. **출처**: 근거마다 `(증권사, 발행일, 제목, [p.N])` 를 붙인다. `[p.N]` 은 본문 속 페이지 표시 그대로다.

## 제약 (스크립트가 강제함)

- SELECT/WITH 단일 문장만. 쓰기 키워드가 있으면 거부(종료코드 3).
  문자열 안에 `drop` 같은 단어가 있어도 거부되니 `ILIKE '%dr_p%'` 처럼 바꿔 쓴다.
- 문자열 리터럴 안에 `--`, `/*`, `;` 를 넣지 않는다.
- sql/schema 는 postgres 소스, ls/fetch 는 s3 소스에만 쓴다 (틀리면 종료코드 1).
- 기본 200행, 최대 5,000행 (`--csv` 도 동일). 30초 타임아웃.
- 종료코드: 1 접속/실행 오류, 3 SQL 거부.
  종료코드 2 = 환경변수 없음 → 설치 안내. argparse 사용법 오류도 2를 돌려주므로 stderr 에 'usage:' 가 있으면 명령 문법 문제다.
- 조사기관 미지정 질문은 기관 확인 질문 없이 답하지 않는다 (위 3단계).
- `python` 이 "Python was not found" 또는 종료코드 9009로 실패하면 모든 명령에서 `python` 대신 `py -3` 을 쓴다.
- 기관 혼합은 4단계의 계획을 사용자가 확인한 뒤에만 계산하고, 결과에는 항상 `(추정)` 과 계산식을 붙인다.

## 새 소스 추가 (소유자용)

`sources/<이름>.md` 를 만들고 머리에 `name / kind(postgres|s3) / env / tables / summary` 를 적은 뒤,
해당 환경변수를 `install.ps1` 의 `$EnvVars` 에 추가한다. 코드 수정 없음.
