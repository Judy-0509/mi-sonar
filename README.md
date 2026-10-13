<p align="center"><img src="assets/banner.png" alt="mi-sonar" width="100%"></p>

<p align="center">Claude Code / OpenCode에서 스마트폰 시장 데이터를 말로 물어보세요.</p>

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

## 이렇게 물어보세요

- "2026년 2분기 제조사별 점유율 보여줘"
- "갤럭시 S 시리즈 최근 8개 분기 출하량 추세, 차트로"
- "작년 동기 대비 가장 많이 성장한 모델 TOP 10"
- "이 데이터의 원본 파일 받아줘"
- "mi-sonar 설치 확인해줘"

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
