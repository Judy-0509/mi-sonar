<#
mi-sonar installer / updater (Windows, PowerShell 5.1+)
Install (README one-liner):  git clone <repo-url> "$HOME\.claude\skills\mi-sonar"; powershell -ExecutionPolicy Bypass -File "$HOME\.claude\skills\mi-sonar\install.ps1"
Update (second half only):   powershell -ExecutionPolicy Bypass -File "$HOME\.claude\skills\mi-sonar\install.ps1"
Local test:                  .\install.ps1 -NoEnv
#>
param(
    [string]$Dest = $PSScriptRoot,   # the cloned skill folder this script lives in
    [switch]$NoEnv
)
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# ---- connection info shared by the whole team (repo must stay private) ----
$EnvVars = @{
    MI_DB_SMARTPHONE = "__FILL_DSN__"     # postgresql://USER:PASSWORD@HOST:5432/DBNAME (URL-encode special chars in PASSWORD)
    MI_MINIO         = "__FILL_MINIO__"   # http://ACCESS:SECRET@HOST:9000/BUCKET (URL-encode special chars in SECRET)
}

function Step($msg) { Write-Host "[mi-sonar] $msg" -ForegroundColor Cyan }

# 1. update the skill folder (the README one-liner cloned it)
if (-not (Test-Path (Join-Path $Dest ".git"))) {
    throw "스킬 폴더가 git clone으로 받은 폴더가 아닙니다. README의 설치 한 줄을 다시 실행하세요."
}
Step "업데이트: git pull"
git -C $Dest pull --ff-only
if ($LASTEXITCODE) { throw "git pull 실패 (exit $LASTEXITCODE)" }

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

# 4. self-check (OpenCode reads ~/.claude/skills natively: no extra registration)
& $py -c "import psycopg, minio"
if ($LASTEXITCODE) { throw "패키지 확인(import psycopg, minio) 실패 (exit $LASTEXITCODE)" }
& $py (Join-Path $Dest "scripts\query.py") sources
if ($LASTEXITCODE) { throw "query.py sources 실패 (exit $LASTEXITCODE)" }
Write-Host ""
Write-Host "설치 완료. 새 터미널을 열고 Claude 또는 OpenCode에게 'mi-sonar 설치 확인해줘' 라고 하세요." -ForegroundColor Green
