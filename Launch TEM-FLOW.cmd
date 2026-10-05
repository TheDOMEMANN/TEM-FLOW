@echo off
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\source_workspace.ps1" -Action Launch
if errorlevel 1 pause
