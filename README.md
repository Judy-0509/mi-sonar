<p align="center"><img src="assets/banner.png" alt="mi-sonar" width="100%"></p>

<p align="center">Claude Code / OpenCode에서 MI 시장 데이터를 말로 물어보고, 보고 자료 초안까지 받으세요.</p>

<p align="center">
  <img alt="python" src="assets/badges/python.svg">
  <img alt="postgres" src="assets/badges/postgres.svg">
  <img alt="minio" src="assets/badges/minio.svg">
  <img alt="agent" src="assets/badges/agent.svg">
  <img alt="tests" src="assets/badges/tests.svg">
</p>

## 설치

### Claude Code (플러그인)

1. Claude Code 입력창에 차례로 입력:

   ```text
   /plugin marketplace add __REPO_URL__
   /plugin install mi-sonar@mi-sonar
   ```

2. Claude 에게 `mi-sonar 설치 확인해줘` 라고 하면 `install.ps1` 실행 명령(경로 포함)을 알려줍니다.
   그 명령을 PowerShell 에서 **한 번** 실행합니다 (Python 패키지 + 접속 환경변수 등록):

   ```powershell
   powershell -ExecutionPolicy Bypass -File "<안내받은 경로>\install.ps1"
   ```

3. **새 터미널**에서 Claude Code 를 다시 열고 `mi-sonar 설치 확인해줘`.

### OpenCode

PowerShell 에 한 줄 붙여넣기 (`~/.claude/skills/mi-sonar` 에 스킬 링크를 만듭니다):

```powershell
git clone __REPO_URL__ "$HOME\.claude\mi-sonar"; powershell -ExecutionPolicy Bypass -File "$HOME\.claude\mi-sonar\install.ps1" -OpenCode
```

끝나면 **새 터미널**에서 OpenCode 를 열고 `mi-sonar 설치 확인해줘`.

### 업데이트

- Claude Code: `/plugin update mi-sonar@mi-sonar` (새 버전이 안 보이면 먼저 `claude plugin marketplace update mi-sonar`).
- OpenCode: 설치 명령의 뒤쪽 절반을 다시 실행 (`git pull` 포함):
  `powershell -ExecutionPolicy Bypass -File "$HOME\.claude\mi-sonar\install.ps1" -OpenCode`
- 예전 방식(`~/.claude/skills/mi-sonar` 에 직접 clone)으로 설치했다면 그 폴더를 지우고 위 방법으로 다시 설치하세요.

설치가 하는 일: Python 패키지를 설치하고, 접속 정보를 내 계정 환경변수(`MI_DB_SMARTPHONE`, `MI_MINIO`)에 넣습니다.
`-OpenCode` 를 붙이면 `~/.claude/skills/mi-sonar` 링크도 만듭니다 (Claude Code 는 플러그인으로 스킬을 받으므로 링크를 만들지 않습니다).

## 무엇을 할 수 있나요

설치 후에는 따로 부르지 않아도 됩니다. 아래처럼 평소 말로 요청하면 Claude가 알아서 이 스킬을 읽고 움직입니다.

| 이렇게 말하면 | Claude가 하는 일 | 지금 상태 |
|---|---|---|
| "2026년 2분기 제조사별 점유율 보여줘"<br>"갤럭시 S 최근 8분기 출하량 추세" | 스마트폰 시장 데이터(smartphone_market_data)를 SQL로 조회해 표·차트와 함께 답하고, 쓴 SQL을 보여줌 | 사용 가능 |
| "이 데이터 원본 파일 받아줘" | MinIO에서 원본 파일을 내려받음 | 사용 가능 |
| "삼성 관련 증권사 레포트 최근 3건 요약"<br>"애널리스트가 AP 가격에 대해 뭐라고 했어?" | 적재된 증권사 레포트에서 찾아 요약·핵심 숫자를 페이지 번호와 함께 인용 | 테이블 생성 대기 (없으면 "테이블 미생성"이라고 알려줌) |
| "스마트워치 TAM 점검해줘" | 최신 TechInsights 실적 vs 우리 TAM 표, 전망 변화 표, 특이사항 메모, "다음 갱신 시 반영 검토" 목록. 갱신이 없는 분기는 기사·레포트 기반 정성 메모만 | 테이블 생성 대기 |
| "스마트워치 자료 한 장 만들어줘" | 자료 규칙(`design/slide-rules.md`)과 사내 말투 샘플대로 쟁점 문장·카드 제목·bullet을 먼저 보여주고 확인 후 슬라이드 파일 생성 | 사용 가능 (말투 샘플은 담당자가 채움) |
| "mi-sonar 설치 확인해줘" | 환경변수·접속·테이블 상태 점검 | 사용 가능 |

### 어떻게 알아서 반응하나요

- Claude Code를 켤 때마다 플러그인이 "MI 데이터·자료 요청은 mi-sonar 절차대로"라는 짧은 안내를 Claude에게 넣어줍니다(세션 시작 안내).
- 스킬 설명에 "출하량, 점유율, 증권사 레포트, 스마트워치 TAM, 자료 만들어 …" 같은 말이 적혀 있어서, 요청에 그런 말이 있으면 Claude가 스킬 본문(5가지 절차)을 읽고 그대로 따릅니다.
- 직접 부르고 싶으면 `/mi-sonar:mi-sonar` 라고 치면 됩니다. OpenCode는 `~/.claude/skills/mi-sonar`를 자동으로 읽습니다.

Claude가 쓴 SQL은 답변에 같이 나옵니다. 읽기전용 계정이라 데이터는 바뀌지 않습니다.

## 문제 해결

- `환경변수 ... 설정되지 않았습니다` → `install.ps1` 을 다시 실행하고 **새 터미널**을 여세요.
- `timeout` / 30초 초과 → 기간이나 모델을 좁히거나 집계(GROUP BY)로 물어보세요.
- `python` 을 찾을 수 없음 → python.org 설치 시 'Add python.exe to PATH' 체크, 또는 `py -3` 사용 (Python 3.10 이상).
- `git` 을 찾을 수 없음 → Git for Windows 설치 후 다시 실행.

## 소유자: 레포 구조·테스트·배포

```text
.claude-plugin/plugin.json        플러그인 정보 (version)
.claude-plugin/marketplace.json   마켓플레이스 (source "./", version)
hooks/                            SessionStart 안내 (session_start.py)
skills/mi-sonar/SKILL.md          스킬 본문
skills/mi-sonar/scripts/          query.py (읽기전용 조회) + 테스트
skills/mi-sonar/sources/          소스 정의 (*.md)
skills/mi-sonar/design/           자료(슬라이드) 규칙·테마·템플릿
tools/                            소유자용 적재·점검 도구
install.ps1                       패키지·환경변수 설치 (OpenCode 는 -OpenCode)
```

테스트: 레포 루트에서 `python -m pytest -q` (`pip install -r requirements-dev.txt` 필요).

배포 규칙: 릴리스마다 `.claude-plugin/plugin.json` 과 `.claude-plugin/marketplace.json` **두 곳의 `version` 을 함께 올린다**.
올리지 않으면 이미 설치한 사람은 `/plugin update` 를 해도 새 버전을 받지 못한다.

## 소유자: 소스 추가

`skills/mi-sonar/sources/<이름>.md` 하나 + `install.ps1`의 `$EnvVars` 한 줄. 자세한 내용은 `skills/mi-sonar/SKILL.md` 끝 부분.

## 소유자: DB 상황 확인

새 테이블을 설계하기 전에 사내 PC에서 `tools/db_check.py` 를 한 번 실행해 DBaaS 계정으로 무엇을 할 수 있는지 확인합니다 (모든 변경은 롤백).
절차, 사용할 계정, 결과 해석은 `docs/handoff/db-capability-check.md` 에 있습니다.
