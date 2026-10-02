@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\source_workspace.ps1" -Action Stop
set "TEMFLOW_RESULT=%ERRORLEVEL%"
if not "%TEMFLOW_RESULT%"=="0" pause
exit /b %TEMFLOW_RESULT%
