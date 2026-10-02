@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\source_workspace.ps1" -Action Check
set "TEMFLOW_RESULT=%ERRORLEVEL%"
pause
exit /b %TEMFLOW_RESULT%
