<#
.SYNOPSIS
  One-time setup for PYQ Analyzer on Windows: tools, Python + Node packages, local OCR model.

.DESCRIPTION
  Installs what is missing (winget / the official uv installer), creates backend\.venv,
  installs the backend and frontend packages, starts Ollama and pulls the OCR model.
  Safe to re-run: anything already present is kept. Works from any folder the project is in.

  Easiest: double-click install.cmd (it bypasses the execution policy and keeps the window open).

.PARAMETER SkipModels   Do not pull Ollama models (e.g. on a metered connection).
.PARAMETER WithV1Models Also pull the models used by the classic (v1) pages (several GB more).
.PARAMETER Test         Run the backend test suite at the end.
#>
param(
    [switch]$SkipModels,
    [switch]$WithV1Models,
    [switch]$Test
)

$ErrorActionPreference = "Stop"
# Folder this script lives in - every path below is relative to it, so any drive/folder works.
$Root = $PSScriptRoot
if (-not $Root) { $Root = Split-Path -Parent $MyInvocation.MyCommand.Path }
$Backend = Join-Path $Root "backend"
$Frontend = Join-Path $Root "frontend"
$VenvPy = Join-Path $Backend ".venv\Scripts\python.exe"
$LogFile = Join-Path $Root "install.log"

# Models (keep in sync with backend\app\config.py)
$OcrModel = "hf.co/sahilchachra/Unlimited-OCR-GGUF:Q4_K_M"
$V1Models = @("huihui_ai/gemma-4-abliterated:e4b", "moondream:latest")

function Step($msg) { Write-Host ""; Write-Host "==> $msg" -ForegroundColor Cyan }
function Ok($msg) { Write-Host "    ok  $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host "    !!  $msg" -ForegroundColor Yellow }
function Have($cmd) { return [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }

function Should-Pause {
    # Keep the window open when started by double-click / install.cmd, so messages can be read.
    if ($env:PYQ_PAUSE -eq "1") { return $true }
    try {
        $parent = (Get-CimInstance Win32_Process -Filter "ProcessId=$PID").ParentProcessId
        $name = (Get-Process -Id $parent -ErrorAction SilentlyContinue).ProcessName
        return ($name -eq "explorer")
    } catch { return $false }
}

function Refresh-Path {
    $machine = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $user = [Environment]::GetEnvironmentVariable("Path", "User")
    $extra = @(
        (Join-Path $env:USERPROFILE ".local\bin"),
        (Join-Path $env:ProgramFiles "nodejs"),
        (Join-Path $env:LOCALAPPDATA "Programs\Ollama"),
        (Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Links")
    ) -join ";"
    $env:Path = "$machine;$user;$extra"
}

function Native($what) {
    # Fail loudly when a native command (uv, npm, ollama) returns an error code.
    if ($LASTEXITCODE -ne 0) { throw "$what failed (exit code $LASTEXITCODE)" }
}

function Winget-Install($id, $name) {
    if (-not (Have "winget")) {
        throw "$name is missing and winget is not available. Install $name manually, then run install again."
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

$pause = Should-Pause
$failed = $false
try { Start-Transcript -Path $LogFile -Force | Out-Null } catch { }

try {
    Write-Host "PYQ Analyzer setup in: $Root"

    # ---- 1. tools ----------------------------------------------------------
    Step "Checking tools"
    Refresh-Path

    if (-not (Have "uv")) {
        Write-Host "    installing uv (Python manager) from astral.sh..."
        & powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex" | Out-Host
        Refresh-Path
    }
    if (Have "uv") { Ok "uv found" } else { throw "uv could not be installed (see https://docs.astral.sh/uv/)" }

    if (-not (Have "node")) { Winget-Install "OpenJS.NodeJS.LTS" "Node.js LTS" }
    if (Have "node") { Ok "node $(node --version)" } else { throw "Node.js not found after install - close this window and run install again" }

    if (-not (Have "ollama")) { Winget-Install "Ollama.Ollama" "Ollama" }
    if (Have "ollama") { Ok "ollama found" } else { throw "Ollama not found after install - close this window and run install again" }

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

    # ---- 2. backend --------------------------------------------------------
    Step "Backend: Python 3.12 virtual environment + packages"
    if (-not (Test-Path $VenvPy)) {
        uv venv (Join-Path $Backend ".venv") --python 3.12 | Out-Host
        Native "uv venv"
    }
    uv pip install --python $VenvPy -r (Join-Path $Backend "pyproject.toml") --extra dev | Out-Host
    Native "uv pip install"
    & $VenvPy -c "import fastapi, sqlalchemy, pypdfium2, matplotlib"
    Native "backend import check"
    Ok "backend packages"

    $envFile = Join-Path $Backend ".env"
    $example = Join-Path $Backend ".env.example"
    if (-not (Test-Path $envFile) -and (Test-Path $example)) {
        Copy-Item $example $envFile
        Ok "created backend\.env from .env.example (all settings optional)"
    }

    # ---- 3. frontend -------------------------------------------------------
    Step "Frontend: npm packages"
    Push-Location $Frontend
    try {
        if (Test-Path "package-lock.json") { & npm.cmd ci --no-fund --no-audit | Out-Host } else { & npm.cmd install --no-fund --no-audit | Out-Host }
        Native "npm install"
        Ok "frontend packages"
    } finally { Pop-Location }

    # ---- 4. models ---------------------------------------------------------
    if ($SkipModels) {
        Step "Skipping model download (-SkipModels)"
    } else {
        Step "Local OCR model (Ollama)"
        if (-not (Port-Open 11434)) {
            Write-Host "    starting ollama serve..."
            Start-Process -WindowStyle Hidden -FilePath "ollama" -ArgumentList "serve" | Out-Null
            for ($i = 0; $i -lt 30 -and -not (Port-Open 11434); $i++) { Start-Sleep -Seconds 1 }
        }
        if (-not (Port-Open 11434)) { throw "Ollama is not answering on port 11434 - start the Ollama app and run install again" }
        $models = @($OcrModel)
        if ($WithV1Models) { $models += $V1Models }
        foreach ($m in $models) {
            Write-Host "    pulling $m (first time can take a while)..."
            ollama pull $m | Out-Host
            Native "ollama pull $m"
            Ok $m
        }
    }

    # ---- 5. check ----------------------------------------------------------
    if ($Test) {
        Step "Backend tests"
        Push-Location $Backend
        try { & $VenvPy -m pytest -q | Out-Host; Native "tests" } finally { Pop-Location }
    }

    Step "Done"
    Write-Host "    Start the app: double-click start-app.cmd   (or: powershell -ExecutionPolicy Bypass -File .\start.ps1)"
    Write-Host "    The database is created / migrated automatically on first start."
} catch {
    $failed = $true
    Write-Host ""
    Write-Host "SETUP FAILED: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Full log: $LogFile"
} finally {
    try { Stop-Transcript | Out-Null } catch { }
    if ($pause) { Write-Host ""; Read-Host "Press Enter to close" | Out-Null }
}
if ($failed) { exit 1 }
