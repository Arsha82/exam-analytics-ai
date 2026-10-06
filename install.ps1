<#
.SYNOPSIS
  One-time setup for PYQ Analyzer on Windows: tools, Python + Node dependencies, local OCR model.

.DESCRIPTION
  Installs what is missing (via winget / the official uv installer), creates backend\.venv,
  installs the backend and frontend packages, starts Ollama and pulls the OCR model.
  Safe to re-run: anything already present is kept.

.PARAMETER SkipModels   Do not pull Ollama models (e.g. on a metered connection).
.PARAMETER WithV1Models Also pull the models used by the classic (v1) pages (several GB more).
.PARAMETER Test         Run the backend test suite at the end.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\install.ps1
#>
param(
    [switch]$SkipModels,
    [switch]$WithV1Models,
    [switch]$Test
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Backend = Join-Path $Root "backend"
$Frontend = Join-Path $Root "frontend"
$VenvPy = Join-Path $Backend ".venv\Scripts\python.exe"

# Models (keep in sync with backend\app\config.py)
$OcrModel = "hf.co/sahilchachra/Unlimited-OCR-GGUF:Q4_K_M"
$V1Models = @("huihui_ai/gemma-4-abliterated:e4b", "moondream:latest")

function Step($msg) { Write-Host ""; Write-Host "==> $msg" -ForegroundColor Cyan }
function Ok($msg) { Write-Host "    ok  $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host "    !!  $msg" -ForegroundColor Yellow }

function Have($cmd) { return [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }

function Refresh-Path {
    $machine = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $user = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machine;$user;$env:USERPROFILE\.local\bin"
}

function Winget-Install($id, $name) {
    if (-not (Have "winget")) {
        throw "$name is missing and winget is not available. Install $name manually, then re-run."
    }
    Write-Host "    installing $name ($id) with winget..."
    winget install --id $id -e --accept-source-agreements --accept-package-agreements --silent | Out-Host
    Refresh-Path
}

function Port-Open($port) {
    try {
        $c = New-Object System.Net.Sockets.TcpClient
        $c.Connect("127.0.0.1", $port)
        $c.Close()
        return $true
    } catch { return $false }
}

# ── 1. tools ──────────────────────────────────────────────────────────
Step "Checking tools"
Refresh-Path

if (-not (Have "uv")) {
    Write-Host "    installing uv (Python manager) from astral.sh..."
    powershell -ExecutionPolicy Bypass -NoProfile -Command "irm https://astral.sh/uv/install.ps1 | iex" | Out-Host
    Refresh-Path
}
if (Have "uv") { Ok "uv $((uv --version) -replace 'uv ','')" } else { throw "uv could not be installed" }

if (-not (Have "node")) { Winget-Install "OpenJS.NodeJS.LTS" "Node.js LTS" }
if (Have "node") { Ok "node $(node --version)" } else { throw "Node.js not found after install (open a new terminal and re-run)" }

if (-not (Have "ollama")) { Winget-Install "Ollama.Ollama" "Ollama" }
if (Have "ollama") { Ok "ollama $((ollama --version) -join ' ')" } else { throw "Ollama not found after install (open a new terminal and re-run)" }

if (-not (Have "ffmpeg")) {
    try { Winget-Install "Gyan.FFmpeg" "FFmpeg" } catch { Warn "FFmpeg not installed: $($_.Exception.Message)" }
}
if (Have "ffmpeg") { Ok "ffmpeg (lesson videos)" } else { Warn "ffmpeg missing - lesson MP4 export will be unavailable" }

if (Have "agy") {
    Ok "agy CLI (web search + repair of flagged questions)"
} else {
    Warn "agy CLI not found. The app still works local-only (uploads, DSpace, local OCR),"
    Warn "but web search and repair of hard scans need the Antigravity 'agy' CLI on PATH, signed in."
}
if (Have "podman") { Ok "podman (optional)" }

# ── 2. backend ────────────────────────────────────────────────────────
Step "Backend: Python 3.12 virtual environment + packages"
if (-not (Test-Path $VenvPy)) {
    uv venv (Join-Path $Backend ".venv") --python 3.12 | Out-Host
}
uv pip install --python $VenvPy -r (Join-Path $Backend "pyproject.toml") --extra dev | Out-Host
& $VenvPy -c "import fastapi, sqlalchemy, pypdfium2, matplotlib; print('    ok  backend packages import')"

$envFile = Join-Path $Backend ".env"
if (-not (Test-Path $envFile)) {
    @(
        "# Local overrides for backend\app\config.py (any setting can be set here)",
        "# OLLAMA_BASE_URL=http://127.0.0.1:11434",
        "# AGY_BIN=agy"
    ) | Set-Content -Encoding utf8 $envFile
    Ok "created backend\.env (all settings optional)"
}

# ── 3. frontend ───────────────────────────────────────────────────────
Step "Frontend: npm packages"
Push-Location $Frontend
try {
    if (Test-Path "package-lock.json") { npm ci --no-fund --no-audit | Out-Host } else { npm install --no-fund --no-audit | Out-Host }
    if ($LASTEXITCODE -ne 0) { throw "npm install failed" }
    Ok "frontend packages"
} finally { Pop-Location }

# ── 4. models ─────────────────────────────────────────────────────────
if ($SkipModels) {
    Step "Skipping model download (-SkipModels)"
} else {
    Step "Local OCR model (Ollama)"
    if (-not (Port-Open 11434)) {
        Write-Host "    starting ollama serve..."
        Start-Process -WindowStyle Hidden -FilePath "ollama" -ArgumentList "serve" | Out-Null
        for ($i = 0; $i -lt 30 -and -not (Port-Open 11434); $i++) { Start-Sleep -Seconds 1 }
    }
    if (-not (Port-Open 11434)) { throw "Ollama is not answering on port 11434" }
    $models = @($OcrModel)
    if ($WithV1Models) { $models += $V1Models }
    foreach ($m in $models) {
        Write-Host "    pulling $m (first time can take a while)..."
        ollama pull $m | Out-Host
        if ($LASTEXITCODE -ne 0) { throw "ollama pull $m failed" }
        Ok $m
    }
}

# ── 5. check ──────────────────────────────────────────────────────────
if ($Test) {
    Step "Backend tests"
    Push-Location $Backend
    try { & $VenvPy -m pytest -q | Out-Host } finally { Pop-Location }
}

Step "Done"
Write-Host "    Start the app with:  powershell -ExecutionPolicy Bypass -File .\start.ps1"
Write-Host "    (the database is created / migrated automatically on first start)"
