# mi-sonar 설계 스펙

작성일: 2026-10-13
상태: 사용자 검토 대기

## 1. 목적

MI 그룹(Sales, System LSI) 비개발자 동료가 Claude Code 터미널에서 자연어로
스마트폰 시장 데이터를 조회·집계·추세 분석하고, 필요하면 MinIO 원본 파일까지
내려받을 수 있게 하는 Claude Code 스킬.

장기적으로 증권사 레포트, 내부 주간보고 등 별도 DB가 추가되어도
**코드 수정 없이 설명 파일 1개 + 환경변수로 소스를 추가**할 수 있는 구조.

## 2. 확정된 전제

| 항목 | 결정 |
|---|---|
| 사용자 | 비개발자 동료, Claude Code 터미널, 전원 Windows |
| DB | PostgreSQL (타팀 DBaaS), 테이블 1개 `smartphone_market_data`, 수십만~수백만 행 |
| 접속 권한 | 공용 읽기전용 계정 1개 공유 (전원 동일 ID/PW) |
| 원본 | MinIO. 테이블에 원본 객체 경로/키 컬럼 존재 |
| 질문 유형 | 조회·집계(모델/기간/점유율), 비교·추세(YoY, 차트, 요약) |
| 실행 환경 | Python 사용 가능 (3.10+) |
| 배포 | 사내 GitHub **비공개 저장소** (설치 스크립트에 공용 계정 정보 포함되므로 필수) |
| 스킬 이름 | `mi-sonar` |

## 3. 폴더 구조

```
mi-sonar/
├── SKILL.md                 에이전트용: 언제 쓰는지 + 작업 순서
├── README.md                동료용: 배너 + 설치 한 줄 + 사용 예
├── install.ps1              설치 스크립트 (복사 한 줄이 이걸 실행)
├── requirements.txt         psycopg[binary], minio
├── assets/
│   └── banner.png           픽셀아트 배너 (README 상단)
├── scripts/
│   ├── query.py             유일한 실행 파일
│   └── test_query.py        DB 없이 도는 가드·파서 테스트
└── sources/
    ├── smartphone.md        PostgreSQL 소스 설명
    └── minio.md             MinIO 원본 소스 설명
```

## 4. 소스 설명 파일 (`sources/*.md`)

파일 1개 = 데이터 소스 1개. YAML 머리 + 마크다운 본문.

```markdown
---
name: smartphone
kind: postgres          # postgres | s3
env: MI_DB_SMARTPHONE   # 접속 문자열이 든 환경변수
tables: [smartphone_market_data]
summary: 스마트폰 시장 데이터 (모델/출하량/점유율 등)
---
## 컬럼 의미
(구현 시 `query.py schema smartphone` 출력으로 뼈대를 만들고, 의미는 소유자가 채움)

## 자주 쓰는 쿼리
...

## 주의사항
- 원본 파일 키 컬럼: `<컬럼명>` → `query.py fetch minio <키>` 로 다운로드
```

MinIO 소스:

```markdown
---
name: minio
kind: s3
env: MI_MINIO            # 형식: http(s)://ACCESS:SECRET@host:9000/bucket
summary: smartphone_market_data 원본 파일 저장소
---
```

`query.py`는 머리 부분만 읽어 접속 방식(kind)과 환경변수(env)를 결정한다.
**소스 추가 = md 파일 1개 + 환경변수 1개. 코드 수정 없음.**

## 5. `scripts/query.py`

| 명령 | 동작 |
|---|---|
| `sources` | `sources/*.md` 목록, 각 소스의 환경변수 설정 여부(값은 숨김) |
| `schema <source>` | `information_schema`에서 테이블·컬럼·타입 조회 + 각 테이블 샘플 3행 |
| `sql <source> "<SQL>" [--limit N] [--csv 경로]` | 안전검사 후 실행. 표(markdown)로 출력. `--csv` 지정 시 파일 저장 |
| `fetch <source> <객체키> [--out 경로]` | MinIO 객체 다운로드. 기본 저장 위치는 현재 폴더 |
| `ls <source> [접두어]` | MinIO 객체 목록 (최대 200개) |

### 안전장치 (코드에 고정, 옵션으로 끌 수 없음)

- SQL은 주석 제거 후 `SELECT` 또는 `WITH`로 시작하는 **단일 문장**만 허용.
  세미콜론은 끝에 하나만 허용.
- 단어 경계 기준으로 `INSERT UPDATE DELETE DROP ALTER TRUNCATE GRANT REVOKE CREATE COPY` 포함 시 거부.
- 연결을 읽기전용 트랜잭션으로 연다 (계정 권한과 이중 방어).
- `statement_timeout` 30초.
- 행 제한: 기본 200, `--limit` 최대 5,000. 초과 시 잘라내고
  "결과가 잘렸습니다. SQL에서 집계하거나 --csv로 저장하세요" 안내.
- 접속 정보는 환경변수에서만 읽음. 출력·오류 메시지에 비밀번호 노출 금지.

### 오류 처리

- 환경변수 없음 → "README의 설치 한 줄을 다시 실행하고 터미널을 재시작하세요" 안내 후 종료코드 2
- 접속 실패/타임아웃 → 원인 한 줄 + 종료코드 1
- 안전검사 실패 → 거부 사유 + 종료코드 3

## 6. `SKILL.md` (에이전트 작업 순서)

frontmatter `description`에 트리거 키워드: 스마트폰 시장 데이터, 출하량, 점유율,
모델별/분기별 수치, smartphone_market_data, 원본 파일, MinIO, mi-sonar.

본문 절차:
1. `query.py sources`로 소스 확인. 환경변수 미설정이면 설치 안내 후 중단.
2. 해당 소스 md의 컬럼 의미를 읽고, 세션당 1회 `query.py schema`로 실제 컬럼 확인.
3. **DB에서 집계**하는 SQL 작성. 원시 행을 통째로 가져오지 않는다.
4. 결과 가공: 표는 그대로, 추세·YoY·차트는 결과를 pandas/matplotlib로 처리.
5. 원본이 필요하면 키 컬럼 값으로 `query.py fetch minio <키>`.
6. 답변에 사용한 SQL을 함께 보여준다 (동료가 재현·검증 가능).

## 7. 설치 (`README.md` + `install.ps1`)

README 최상단: 배너 이미지 → 바로 아래 복사 한 줄.

```powershell
powershell -ExecutionPolicy Bypass -c "irm https://<사내GitHub>/<org>/mi-sonar/raw/main/install.ps1 | iex"
```

`install.ps1`이 하는 일 (재실행 시 업데이트로 동작):
1. `git clone` 또는 이미 있으면 `git pull` → `~/.claude/skills/mi-sonar`
   (git 없으면 zip 다운로드로 대체)
2. `pip install -r requirements.txt`
3. `setx MI_DB_SMARTPHONE "..."`, `setx MI_MINIO "..."` (값은 스크립트에 내장).
   사용자 수준 환경변수이므로 Claude Code와 OpenCode 모두 새 터미널에서 자동으로 읽는다.
4. OpenCode 전역 스킬 폴더 `~/.config/opencode/skill/mi-sonar`에 정션(junction)을 만들어
   같은 폴더가 양쪽 도구에 등록되게 한다.
5. "새 터미널을 열고 Claude 또는 OpenCode에게 `mi-sonar 설치 확인해줘`라고 하세요" 출력

README 나머지: 사용 예시 질문 5개, 문제 해결 3줄(환경변수 안 잡힘 → 터미널 재시작 등).

## 8. 배너 (`assets/banner.png`)

- 픽셀아트 스타일, 1200×300 내외
- 큰 픽셀 글자 "MI-SONAR" + 한 줄 설명. 작은 글자·장식보다 가독성 우선
- 구현 시 이미지 생성 도구로 제작, 소유자 검수 후 확정

## 9. 테스트

- `scripts/test_query.py` (DB 불필요): SQL 가드 허용/거부 케이스, 머리 부분 파서, 행 제한 잘림
- 수동 통합 점검: 실제 DB로 `sources` → `schema` → `sql` → `fetch` 한 번씩

## 10. 범위 밖 (나중에)

- 증권사 레포트 DB: 저장 방식 확정 후 `sources/reports.md` + 필요 시 `search` 명령 추가
- 내부 주간보고: 동일 패턴
- 사람별 계정, API 서버, MCP 전환: 공용 계정 정책이 바뀔 때

## 11. 작업 분할: 사외(지금) vs 사내 에이전트

사내망·실제 DB·사내 GitHub가 필요한 일은 **사내 에이전트에게 작업지시서로 위임**한다.
저장소 루트 = 스킬 루트 (clone 하면 바로 `~/.claude/skills/mi-sonar`).

| 사외에서 지금 | 사내 에이전트 (`docs/handoff/internal-agent-order.md`) |
|---|---|
| query.py, 테스트, SKILL.md, sources 뼈대, README, 배너, install.ps1(자리표시자) | install.ps1의 저장소 URL·DB·MinIO 접속 정보 채우기 |
| | `query.py schema smartphone` 실행 → `sources/smartphone.md` 컬럼 표 채우기, 원본 키 컬럼명 기입 |
| | 사내 GitHub 비공개 저장소에 push, 깨끗한 PC에서 설치 한 줄 검증 |
| | 실제 DB로 `sources → schema → sql → ls → fetch` 통합 점검 |
