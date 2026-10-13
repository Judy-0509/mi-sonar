<p align="center"><img src="assets/banner.png" alt="mi-sonar" width="100%"></p>

<p align="center">Claude Code / OpenCode에서 스마트폰 시장 데이터를 말로 물어보세요.</p>

<p align="center">
  <img alt="python" src="https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white">
  <img alt="postgres" src="https://img.shields.io/badge/postgres-read--only-336791?logo=postgresql&logoColor=white">
  <img alt="minio" src="https://img.shields.io/badge/storage-minio-C72C48?logo=minio&logoColor=white">
  <img alt="agent" src="https://img.shields.io/badge/agent-claude%20code%20%C2%B7%20opencode-D97757">
  <img alt="tests" src="https://img.shields.io/badge/tests-48%20passing-4C1">
</p>

<p align="center"><sub>🏆 <b>WANT</b> — 받고 싶은 상 (아직 하나도 못 받음)</sub></p>

<p align="center">
  <img alt="want" src="https://img.shields.io/badge/WANT-GitHub%20Trending%20%231-ff69b4">
  <img alt="want" src="https://img.shields.io/badge/WANT-Best%20Repo%20of%202026-gold">
  <img alt="want" src="https://img.shields.io/badge/WANT-10k%20stars%20(%ED%98%84%EC%9E%AC%201)-yellow">
  <img alt="want" src="https://img.shields.io/badge/WANT-%EC%98%AC%ED%95%B4%EC%9D%98%20%EC%82%AC%EB%82%B4%20%ED%88%B4-8A2BE2">
  <img alt="want" src="https://img.shields.io/badge/WANT-%ED%8C%80%EC%9E%A5%EB%8B%98%20%EC%B9%AD%EC%B0%AC%201%ED%9A%8C-2ea44f">
</p>

## 설치: 아래 상자를 복사해서 Claude Code 또는 OpenCode에 그대로 붙여넣으세요

```text
mi-sonar 스킬을 설치해줘. 순서:
1) PowerShell에서 다음 한 줄을 실행: git clone __REPO_URL__ "$HOME\.claude\skills\mi-sonar"; powershell -ExecutionPolicy Bypass -File "$HOME\.claude\skills\mi-sonar\install.ps1"
2) 끝나면 PowerShell로 [Environment]::GetEnvironmentVariable('MI_DB_SMARTPHONE','User') 와 ('MI_MINIO','User') 가 비어 있지 않은지만 확인해줘 (값은 절대 출력하지 말 것).
3) 둘 다 설정됐으면 "설치 완료. 새 터미널을 열고 'mi-sonar 설치 확인해줘'라고 하세요"라고 알려주고, 아니면 설치 출력의 오류를 보여줘.
```

(GitHub에서 상자 오른쪽 위 복사 버튼을 누르면 됩니다. 직접 하려면 아래 한 줄만 PowerShell에 붙여넣어도 됩니다.)

## 직접 설치 (PowerShell에 한 줄 붙여넣기)

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

## 소유자: DB 상황 확인

새 테이블을 설계하기 전에 사내 PC에서 `tools/db_check.py` 를 한 번 실행해 DBaaS 계정으로 무엇을 할 수 있는지 확인합니다 (모든 변경은 롤백).
절차, 사용할 계정, 결과 해석은 `docs/handoff/db-capability-check.md` 에 있습니다.
