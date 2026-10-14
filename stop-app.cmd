@echo off
rem Double-click to stop PYQ Analyzer.
set PYQ_PAUSE=1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" -Stop
