<#
.SYNOPSIS
  Starts PYQ Analyzer on Windows: Ollama (if needed), the backend API and the web UI.

.PARAMETER Stop        Stop the backend and frontend started by this script.
.PARAMETER NoBrowser   Do not open the browser.
.PARAMETER Port        Backend port (default 8010; the frontend proxies /api to it).

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\start.ps1
  powershell -ExecutionPolicy Bypass -File .\start.ps1 -Stop
#>
param(
    [switch]$Stop,
    [switch]$NoBrowser,
    [int]$Port = 8010
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Backend = Join-Path $Root "backend"
$Frontend = Join-Path $Root "frontend"
$VenvPy = Join-Path $Backend ".venv\Scripts\python.exe"
$RunDir = Join-Path $Root ".run"
$PidFile = Join-Path $RunDir "pids.txt"
$UiUrl = "http://localhost:5173"

function Port-Open($p) {
    try { $c = New-Object System.Net.Sockets.TcpClient; $c.Connect("127.0.0.1", $p); $c.Close(); return $true } catch { return $false }
}
function Wait-Url($url, $seconds) {
    for ($i = 0; $i -lt $seconds; $i++) {
        try { Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 $url | Out-Null; return $true } catch { Start-Sleep -Seconds 1 }
    }
    return $false
}
function Stop-Started {
    if (-not (Test-Path $PidFile)) { Write-Host "Nothing to stop (no $PidFile)."; return }
    foreach ($id in Get-Content $PidFile) {
        if ($id -match '^\d+$') {
            # /T also stops child processes (npm -> node -> vite, uvicorn workers)
            & taskkill.exe /PID $id /T /F 2>$null | Out-Null
        }
    }
    Remove-Item $PidFile -Force
    Write-Host "Stopped PYQ Analyzer (backend + frontend). Ollama is left running."
}

if ($Stop) { Stop-Started; return }

if (-not (Test-Path $VenvPy)) { throw "backend\.venv not found - run .\install.ps1 first" }
if (-not (Test-Path (Join-Path $Frontend "node_modules"))) { throw "frontend\node_modules not found - run .\install.ps1 first" }
New-Item -ItemType Directory -Force $RunDir | Out-Null
if (Test-Path $PidFile) { Stop-Started }
$started = @()

# Ollama (local OCR)
if (Port-Open 11434) {
    Write-Host "ollama    already running"
} elseif (Get-Command ollama -ErrorAction SilentlyContinue) {
    Start-Process -WindowStyle Hidden -FilePath "ollama" -ArgumentList "serve" | Out-Null
    Write-Host "ollama    starting..."
} else {
    Write-Host "ollama    not installed - scanned papers cannot be read locally (run .\install.ps1)" -ForegroundColor Yellow
}

# Backend
if (Port-Open $Port) { throw "Port $Port is already in use. Stop that program or use -Port <other>." }
$be = Start-Process -PassThru -WindowStyle Hidden -FilePath $VenvPy -WorkingDirectory $Backend `
    -ArgumentList @("-m", "uvicorn", "app.main:app", "--port", "$Port") `
    -RedirectStandardOutput (Join-Path $RunDir "backend.log") -RedirectStandardError (Join-Path $RunDir "backend.err.log")
$started += $be.Id
Write-Host "backend   starting on http://127.0.0.1:$Port (log: .run\backend.err.log)"

# Frontend (Vite dev server; proxies /api to the backend)
$env:VITE_API_PORT = "$Port"
$fe = Start-Process -PassThru -WindowStyle Hidden -FilePath "npm.cmd" -WorkingDirectory $Frontend `
    -ArgumentList @("run", "dev") `
    -RedirectStandardOutput (Join-Path $RunDir "frontend.log") -RedirectStandardError (Join-Path $RunDir "frontend.err.log")
$started += $fe.Id
$started | Set-Content $PidFile

if (-not (Wait-Url "http://127.0.0.1:$Port/api/system/status" 90)) {
    Write-Host "backend did not come up - last lines of .run\backend.err.log:" -ForegroundColor Red
    Get-Content (Join-Path $RunDir "backend.err.log") -Tail 20
    Stop-Started
    exit 1
}
Write-Host "backend   ready" -ForegroundColor Green
if (-not (Wait-Url $UiUrl 60)) {
    Write-Host "frontend did not come up - see .run\frontend.log" -ForegroundColor Red
    Stop-Started
    exit 1
}
Write-Host "frontend  ready: $UiUrl" -ForegroundColor Green
if (-not $NoBrowser) { Start-Process $UiUrl }
Write-Host ""
Write-Host "Running in the background. Stop with:  powershell -ExecutionPolicy Bypass -File .\start.ps1 -Stop"
