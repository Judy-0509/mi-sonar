<#
mi-sonar installer / updater (Windows, PowerShell 5.1+). Run once per PC; safe to re-run.

Claude Code (plugin):
  1) in Claude Code:  /plugin marketplace add __REPO_URL__
  2)                  /plugin install mi-sonar@mi-sonar
  3) ask Claude "mi-sonar 설치 확인" -> the session-start hook shows this file's path
  4) run that path once:  powershell -ExecutionPolicy Bypass -File "<plugin folder>\install.ps1"
  Update: /plugin update mi-sonar@mi-sonar   (or `claude plugin marketplace update mi-sonar` first)

OpenCode (clone + junction ~/.claude/skills/mi-sonar):
  git clone __REPO_URL__ "$HOME\.claude\mi-sonar"; powershell -ExecutionPolicy Bypass -File "$HOME\.claude\mi-sonar\install.ps1" -OpenCode
  Update: same command without the clone (git pull runs inside)

Local test:  .\install.ps1 -NoEnv
#>
param(
    [string]$Dest = $PSScriptRoot,   # repo / plugin root this script lives in
    [switch]$NoEnv,
    [switch]$OpenCode                # also link ~/.claude/skills/mi-sonar -> <root>\skills\mi-sonar
)
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# ---- connection info shared by the whole team (repo must stay private) ----
$EnvVars = @{
    MI_DB_SMARTPHONE = "__FILL_DSN__"     # postgresql://USER:PASSWORD@HOST:5432/DBNAME (URL-encode special chars in PASSWORD)
    MI_MINIO         = "__FILL_MINIO__"   # http://ACCESS:SECRET@HOST:9000/BUCKET (URL-encode special chars in SECRET)
}

function Step($msg) { Write-Host "[mi-sonar] $msg" -ForegroundColor Cyan }

# 1. update a git clone (OpenCode install); the Claude Code plugin is updated by /plugin update
if (Test-Path (Join-Path $Dest ".git")) {
    Step "업데이트: git pull"
    git -C $Dest pull --ff-only
    if ($LASTEXITCODE) { throw "git pull 실패 (exit $LASTEXITCODE)" }
}

# 2. Python 3.10+ ("python" may be the Microsoft Store stub, exit 9009 -> try the py launcher) + packages
$noPy = "Python 3.10 이상을 설치하고 'Add python.exe to PATH'를 켠 뒤 다시 실행하세요."
$py = "python"
try { $ver = & python --version 2>$null; $ok = -not $LASTEXITCODE } catch { $ok = $false }
if (-not $ok) {
    try { $ver = & py -3 --version 2>$null; $ok = -not $LASTEXITCODE } catch { $ok = $false }
    if (-not $ok) { throw $noPy }
    $py = & py -3 -c "import sys; print(sys.executable)"
    if ($LASTEXITCODE) { throw "py -3 실패 (exit $LASTEXITCODE)" }
}
if ("$ver" -notmatch 'Python (\d+)\.(\d+)' -or [version]"$($Matches[1]).$($Matches[2])" -lt [version]"3.10") {
    throw "$noPy (현재: $ver)"
}
Step "Python 패키지 설치 ($ver)"
& $py -m pip install --quiet --disable-pip-version-check -r (Join-Path $Dest "requirements.txt")
if ($LASTEXITCODE) { throw "pip install 실패 (exit $LASTEXITCODE)" }

# 3. user-level env vars (Claude Code and OpenCode both inherit these in a new terminal)
if (-not $NoEnv) {
    $unfilled = @($EnvVars.Keys | Where-Object { $EnvVars[$_] -like "__FILL_*" })
    if ($unfilled) { throw "install.ps1 의 $($unfilled -join ', ') 값이 아직 채워지지 않았습니다 (소유자에게 문의)." }
    foreach ($k in $EnvVars.Keys) {
        [Environment]::SetEnvironmentVariable($k, $EnvVars[$k], 'User')
        Set-Item -Path "env:$k" -Value $EnvVars[$k]
    }
    Step "환경변수 등록: $($EnvVars.Keys -join ', ')"
}

# 4. OpenCode only: junction ~/.claude/skills/mi-sonar (Claude Code gets the skill from the plugin; a junction would duplicate it)
$skill = Join-Path $Dest "skills\mi-sonar"
if ($OpenCode) {
    $link = Join-Path $HOME ".claude\skills\mi-sonar"
    $old = Get-Item -LiteralPath $link -Force -ErrorAction SilentlyContinue
    if ($old -and -not ($old.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        Write-Host "[mi-sonar] $link 가 실제 폴더라서 링크를 만들지 않았습니다 (지우지 않음). 이전 방식 설치본이면 직접 지우고 다시 실행하세요." -ForegroundColor Yellow
    } else {
        if ($old) { [IO.Directory]::Delete($link) }   # removes the junction only, never the target's files
        New-Item -ItemType Directory -Force (Split-Path $link) | Out-Null
        New-Item -ItemType Junction -Path $link -Target $skill | Out-Null
        Step "OpenCode 스킬 링크: $link -> $skill"
    }
}

# 5. self-check
& $py -c "import psycopg, minio"
if ($LASTEXITCODE) { throw "패키지 확인(import psycopg, minio) 실패 (exit $LASTEXITCODE)" }
& $py (Join-Path $skill "scripts\query.py") sources
if ($LASTEXITCODE) { throw "query.py sources 실패 (exit $LASTEXITCODE)" }
Write-Host ""
Write-Host "설치 완료. 새 터미널을 열고 Claude 또는 OpenCode에게 'mi-sonar 설치 확인해줘' 라고 하세요." -ForegroundColor Green
