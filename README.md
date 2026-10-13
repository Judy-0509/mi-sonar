![mi-sonar](assets/banner.png)

# mi-sonar

Claude Code / OpenCode에서 스마트폰 시장 데이터를 말로 물어보세요.

## 설치 (PowerShell에 한 줄 붙여넣기)

```powershell
git clone __REPO_URL__ "$HOME\.claude\skills\mi-sonar"; powershell -ExecutionPolicy Bypass -File "$HOME\.claude\skills\mi-sonar\install.ps1"
```

끝나면 **새 터미널**을 열고 Claude 또는 OpenCode에게 `mi-sonar 설치 확인해줘` 라고 하세요.
업데이트는 뒤쪽 절반만 다시 실행하면 됩니다 (`git pull` 로 최신 버전을 받습니다):

```powershell
powershell -ExecutionPolicy Bypass -File "$HOME\.claude\skills\mi-sonar\install.ps1"
```

설치가 하는 일: 스킬을 `~/.claude/skills/mi-sonar`에 받고, Python 패키지를 설치하고,
접속 정보를 내 계정 환경변수(`MI_DB_SMARTPHONE`, `MI_MINIO`)에 넣습니다.
OpenCode는 같은 폴더(~/.claude/skills)를 자동으로 읽으므로 별도 등록이 없다.

## 이렇게 물어보세요

- "2026년 2분기 제조사별 점유율 보여줘"
- "갤럭시 S 시리즈 최근 8개 분기 출하량 추세, 차트로"
- "작년 동기 대비 가장 많이 성장한 모델 TOP 10"
- "이 데이터의 원본 파일 받아줘"
- "mi-sonar 설치 확인해줘"

Claude가 쓴 SQL은 답변에 같이 나옵니다. 읽기전용 계정이라 데이터는 바뀌지 않습니다.

## 문제 해결

- `환경변수 ... 설정되지 않았습니다` → 설치 한 줄을 다시 실행하고 **새 터미널**을 여세요.
- `timeout` / 30초 초과 → 기간이나 모델을 좁히거나 집계(GROUP BY)로 물어보세요.
- `python` 을 찾을 수 없음 → python.org 설치 시 'Add python.exe to PATH' 체크, 또는 `py -3` 사용 (Python 3.10 이상).
- `git` 을 찾을 수 없음 → Git for Windows 설치 후 다시 실행.

## 소유자: 소스 추가

`sources/<이름>.md` 하나 + `install.ps1`의 `$EnvVars` 한 줄. 자세한 내용은 `SKILL.md` 끝 부분.
