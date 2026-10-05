@echo off
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\source_workspace.ps1" -Action Stop
if errorlevel 1 pause
