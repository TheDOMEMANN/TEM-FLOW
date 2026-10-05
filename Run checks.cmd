@echo off
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\source_workspace.ps1" -Action Check
if errorlevel 1 pause
