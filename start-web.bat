@echo off
rem ASCII-only launcher. All logic and messages are in scripts\dev.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\dev.ps1" -Target web
if errorlevel 1 pause
