<#
.SYNOPSIS
  Starts PYQ Analyzer on Windows: Ollama (if needed), the backend API and the web UI.

  Easiest: double-click start-app.cmd (and stop-app.cmd to stop).

.PARAMETER Stop        Stop the backend and frontend started by this script.
.PARAMETER NoBrowser   Do not open the browser.
.PARAMETER Port        Backend port (default 8010; the frontend proxies /api to it).
#>
param(
    [switch]$Stop,
    [switch]$NoBrowser,
    [int]$Port = 8010
)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
if (-not $Root) { $Root = Split-Path -Parent $MyInvocation.MyCommand.Path }
$Backend = Join-Path $Root "backend"
$Frontend = Join-Path $Root "frontend"
$VenvPy = Join-Path $Backend ".venv\Scripts\python.exe"
$RunDir = Join-Path $Root ".run"
$PidFile = Join-Path $RunDir "pids.txt"
$UiUrl = "http://localhost:5173"

function Should-Pause {
    if ($env:PYQ_PAUSE -eq "1") { return $true }
    try {
        $parent = (Get-CimInstance Win32_Process -Filter "ProcessId=$PID").ParentProcessId
        return ((Get-Process -Id $parent -ErrorAction SilentlyContinue).ProcessName -eq "explorer")
    } catch { return $false }
}
function Refresh-Path {
    $machine = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $user = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machine;$user;" + (Join-Path $env:LOCALAPPDATA "Programs\Ollama")
}
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
    if (-not (Test-Path $PidFile)) { Write-Host "Nothing to stop."; return }
    foreach ($id in Get-Content $PidFile) {
        if ($id -match '^\d+$') {
            # /T also stops child processes (npm -> node -> vite)
            # via cmd: in PowerShell 5.1 a redirected native stderr ("process not found") becomes a fatal error
            cmd.exe /c "taskkill /PID $id /T /F >nul 2>&1"
        }
    }
    Remove-Item $PidFile -Force
    Write-Host "Stopped PYQ Analyzer (backend + frontend). Ollama is left running."
}

$pause = Should-Pause
$failed = $false
try {
    Refresh-Path
    if ($Stop) {
        Stop-Started
    } else {
        if (-not (Test-Path $VenvPy)) { throw "backend\.venv not found - run install.cmd (or install.ps1) first" }
        if (-not (Test-Path (Join-Path $Frontend "node_modules"))) { throw "frontend\node_modules not found - run install.cmd first" }
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
            Write-Host "ollama    not installed - scanned papers cannot be read locally (run install.cmd)" -ForegroundColor Yellow
        }

        # Backend
        if (Port-Open $Port) { throw "Port $Port is already in use. Close that program, or run start.ps1 -Port <other>." }
        $be = Start-Process -PassThru -WindowStyle Hidden -FilePath $VenvPy -WorkingDirectory $Backend `
            -ArgumentList @("-m", "uvicorn", "app.main:app", "--port", "$Port") `
            -RedirectStandardOutput (Join-Path $RunDir "backend.log") -RedirectStandardError (Join-Path $RunDir "backend.err.log")
        $started += $be.Id
        Write-Host "backend   starting on http://127.0.0.1:$Port"

        # Frontend (Vite dev server; proxies /api to the backend)
        if (Port-Open 5173) { throw "Port 5173 is already in use (another dev server?). Close it and start again." }
        $env:VITE_API_PORT = "$Port"
        $fe = Start-Process -PassThru -WindowStyle Hidden -FilePath "npm.cmd" -WorkingDirectory $Frontend `
            -ArgumentList @("run", "dev") `
            -RedirectStandardOutput (Join-Path $RunDir "frontend.log") -RedirectStandardError (Join-Path $RunDir "frontend.err.log")
        $started += $fe.Id
        $started | Set-Content $PidFile

        if (-not (Wait-Url "http://127.0.0.1:$Port/api/system/status" 120)) {
            Write-Host "backend did not come up - last lines of .run\backend.err.log:" -ForegroundColor Red
            Get-Content (Join-Path $RunDir "backend.err.log") -Tail 25
            Stop-Started
            throw "backend failed to start"
        }
        Write-Host "backend   ready" -ForegroundColor Green
        if (-not (Wait-Url $UiUrl 90)) {
            Write-Host "frontend did not come up - last lines of .run\frontend.log:" -ForegroundColor Red
            Get-Content (Join-Path $RunDir "frontend.log") -Tail 25
            Stop-Started
            throw "frontend failed to start"
        }
        Write-Host "frontend  ready: $UiUrl" -ForegroundColor Green
        if (-not $NoBrowser) { Start-Process $UiUrl }
        Write-Host ""
        Write-Host "PYQ Analyzer is running in the background (logs in .run\)."
        Write-Host "Stop it with stop-app.cmd  (or: powershell -ExecutionPolicy Bypass -File .\start.ps1 -Stop)"
    }
} catch {
    $failed = $true
    Write-Host ""
    Write-Host "START FAILED: $($_.Exception.Message)" -ForegroundColor Red
} finally {
    if ($pause) {
        Write-Host ""
        if ($failed) { Read-Host "Press Enter to close this window" | Out-Null }
        else { Write-Host "This window closes in 5 seconds (the app keeps running)."; Start-Sleep -Seconds 5 }
    }
}
if ($failed) { exit 1 }
