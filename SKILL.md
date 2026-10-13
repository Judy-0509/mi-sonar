---
name: mi-sonar
description: 스마트폰 시장 데이터(smartphone_market_data) 조회·집계·추세 분석과 MinIO 원본 파일 다운로드. "출하량", "점유율", "판매량", "성장률", "YoY", "모델별/분기별 수치", "제조사", "브랜드", "모델", "갤럭시", "아이폰", "분기", "조사기관", "market share", "shipments", "시장 데이터", "원본 파일", "mi-sonar 설치 확인" 같은 요청에 사용. 모든 DB 접근은 scripts/query.py 로만 한다.
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
4. **집계는 DB에서**: 모델/기간/지역별 수치, 점유율, YoY는 SQL `GROUP BY`로 계산해 작은 결과만 가져온다.
   원시 행을 통째로 가져오지 않는다. "잘렸습니다" 안내가 나오면 더 집계하거나 `--limit` 을 올린다.
   `--csv` 도 같은 행 제한(최대 5,000행)이 걸리므로 잘림을 피하는 방법이 아니다.
5. **가공**: 표는 그대로 보여준다. 추세·차트·요약은 먼저 SQL로 집계하고, 5,000행 이하의 집계 결과만
   `--csv`로 저장해 pandas/matplotlib로 처리한다.
   - pandas/matplotlib가 없으면 사용자에게 알리고 `python -m pip install pandas matplotlib` 를 실행한다.
   - 그리기 전에 `plt.rcParams['font.family']='Malgun Gothic'`, `plt.rcParams['axes.unicode_minus']=False` 를 설정한다.
6. **원본 파일**: 행의 원본 키 컬럼 값으로 `fetch minio <키>`. 위치를 모르면 `ls minio <접두어>`.
7. **답변에 SQL 포함**: 사용한 SQL을 코드블록으로 같이 보여준다(동료가 재현·검증 가능).

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

## 새 소스 추가 (소유자용)

`sources/<이름>.md` 를 만들고 머리에 `name / kind(postgres|s3) / env / tables / summary` 를 적은 뒤,
해당 환경변수를 `install.ps1` 의 `$EnvVars` 에 추가한다. 코드 수정 없음.
