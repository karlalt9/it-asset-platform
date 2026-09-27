@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0pc-health-check.ps1" %*

echo.
pause
