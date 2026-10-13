<#
mi-sonar installer / updater (Windows, PowerShell 5.1+)
Colleagues:  powershell -ExecutionPolicy Bypass -c "irm __REPO_URL__/raw/main/install.ps1 | iex"
Local test:  .\install.ps1 -Repo C:\path\to\repo -Dest $env:TEMP\mi-sonar-test -NoEnv
#>
param(
    [string]$Repo = "__REPO_URL__",   # in-company agent fills: https://github.corp/org/mi-sonar
    [string]$Dest = (Join-Path $HOME ".claude\skills\mi-sonar"),
    [switch]$NoEnv
)
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# ---- connection info shared by the whole team (repo must stay private) ----
$EnvVars = @{
    MI_DB_SMARTPHONE = "__FILL_DSN__"     # postgresql://USER:PASSWORD@HOST:5432/DBNAME
    MI_MINIO         = "__FILL_MINIO__"   # http://ACCESS:SECRET@HOST:9000/BUCKET
}

function Step($msg) { Write-Host "[mi-sonar] $msg" -ForegroundColor Cyan }

# 1. get / update the skill folder
New-Item -ItemType Directory -Force (Split-Path $Dest) | Out-Null
if (Get-Command git -ErrorAction SilentlyContinue) {
    if (Test-Path (Join-Path $Dest ".git")) { Step "업데이트: git pull"; git -C $Dest pull --ff-only }
    else { Step "다운로드: git clone"; git clone --quiet $Repo $Dest }
} else {
    Step "git 없음: zip 다운로드"
    $zip = Join-Path $env:TEMP "mi-sonar.zip"
    Invoke-WebRequest "$($Repo -replace '\.git$','')/archive/refs/heads/main.zip" -OutFile $zip
    $tmp = Join-Path $env:TEMP "mi-sonar-unzip"
    if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
    Expand-Archive $zip $tmp
    if (Test-Path $Dest) { Remove-Item $Dest -Recurse -Force }
    Move-Item (Get-ChildItem $tmp | Select-Object -First 1).FullName $Dest
}

# 2. python deps
Step "Python 패키지 설치"
python -m pip install --quiet --disable-pip-version-check -r (Join-Path $Dest "requirements.txt")

# 3. user-level env vars (Claude Code and OpenCode both inherit these in a new terminal)
if (-not $NoEnv) {
    foreach ($k in $EnvVars.Keys) {
        if ($EnvVars[$k] -like "__FILL_*") { throw "install.ps1 의 $k 값이 아직 채워지지 않았습니다 (소유자에게 문의)." }
        setx $k $EnvVars[$k] | Out-Null
        Set-Item -Path "env:$k" -Value $EnvVars[$k]
    }
    Step "환경변수 등록: $($EnvVars.Keys -join ', ')"
}

# 4. register for OpenCode too (junction to the same folder)
$ocDir = Join-Path $HOME ".config\opencode\skill"
New-Item -ItemType Directory -Force $ocDir | Out-Null
$link = Join-Path $ocDir "mi-sonar"
if (-not (Test-Path $link)) { New-Item -ItemType Junction -Path $link -Target $Dest | Out-Null; Step "OpenCode 등록: $link" }

# 5. self-check
python (Join-Path $Dest "scripts\query.py") sources
Write-Host ""
Write-Host "설치 완료. 새 터미널을 열고 Claude 또는 OpenCode에게 'mi-sonar 설치 확인해줘' 라고 하세요." -ForegroundColor Green
