@echo off
rem Double-click to set up PYQ Analyzer (tools, packages, OCR model).
set PYQ_PAUSE=1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
