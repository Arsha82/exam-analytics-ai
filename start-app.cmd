@echo off
rem Double-click to start PYQ Analyzer (opens http://localhost:5173).
set PYQ_PAUSE=1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" %*
