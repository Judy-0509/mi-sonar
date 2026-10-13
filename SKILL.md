---
name: mi-sonar
description: 스마트폰 시장 데이터(smartphone_market_data) 조회·집계·추세 분석과 MinIO 원본 파일 다운로드. "출하량", "점유율", "모델별/분기별 수치", "YoY", "시장 데이터", "원본 파일", "mi-sonar 설치 확인" 같은 요청에 사용. 모든 DB 접근은 scripts/query.py 로만 한다.
---

# mi-sonar

읽기전용 데이터 조회 스킬. 실행 파일은 `scripts/query.py` 하나뿐이다.
스킬 폴더 경로를 `$S` 라고 할 때 (`~/.claude/skills/mi-sonar`):

| 목적 | 명령 |
|---|---|
| 소스 목록·환경변수 상태 | `python $S/scripts/query.py sources` |
| 테이블 컬럼·샘플 | `python $S/scripts/query.py schema smartphone` |
| SQL 실행 | `python $S/scripts/query.py sql smartphone "SELECT ..." [--limit N] [--csv 파일]` |
| 원본 목록 | `python $S/scripts/query.py ls minio [접두어]` |
| 원본 다운로드 | `python $S/scripts/query.py fetch minio <키> [--out 경로]` |

## 작업 순서

1. **설치 확인**: 세션에서 처음 쓸 때 `sources` 실행. `미설정`이 있으면 사용자에게
   "README 맨 위의 설치 한 줄을 PowerShell에 붙여넣고 새 터미널을 여세요"라고 안내하고 중단.
2. **소스 이해**: `sources/smartphone.md`의 컬럼 의미를 읽는다. 세션당 1회 `schema smartphone`으로
   실제 컬럼을 확인한다(컬럼은 바뀔 수 있다. 문서가 아니라 `schema` 출력이 정답).
3. **집계는 DB에서**: 모델/기간/지역별 수치, 점유율, YoY는 SQL `GROUP BY`로 계산해 작은 결과만 가져온다.
   원시 행을 통째로 가져오지 않는다. 결과가 "잘렸습니다"로 끝나면 집계하거나 `--csv`로 저장한다.
4. **가공**: 표는 그대로 보여준다. 추세·차트·요약은 `--csv`로 저장한 뒤 pandas/matplotlib로 처리한다.
5. **원본 파일**: 행의 원본 키 컬럼 값으로 `fetch minio <키>`. 위치를 모르면 `ls minio <접두어>`.
6. **답변에 SQL 포함**: 사용한 SQL을 코드블록으로 같이 보여준다(동료가 재현·검증 가능).

## 제약 (스크립트가 강제함)

- SELECT/WITH 단일 문장만. 쓰기 키워드가 있으면 거부(종료코드 3).
  문자열 안에 `drop` 같은 단어가 있어도 거부되니 `ILIKE '%dr_p%'` 처럼 바꿔 쓴다.
- 기본 200행, 최대 5,000행. 30초 타임아웃.
- 종료코드: 1 접속/실행 오류, 2 환경변수 없음, 3 SQL 거부.

## 새 소스 추가 (소유자용)

`sources/<이름>.md` 를 만들고 머리에 `name / kind(postgres|s3) / env / tables / summary` 를 적은 뒤,
해당 환경변수를 `install.ps1` 의 `$EnvVars` 에 추가한다. 코드 수정 없음.
