@echo off
setlocal
cd /d "%~dp0"
set "TEMFLOW_PYTHON="
for %%P in ("%~dp0..\Desktop\runtime\python.exe" "%~dp0..\runtime\python.exe" "%~dp0..\.venv\Scripts\python.exe" "%~dp0..\Editable_Source\.venv\Scripts\python.exe" "%~dp0..\Source\.venv\Scripts\python.exe") do if not defined TEMFLOW_PYTHON if exist "%%~P" set "TEMFLOW_PYTHON=%%~P"
if not defined TEMFLOW_PYTHON set "TEMFLOW_PYTHON=python"
"%TEMFLOW_PYTHON%" -B "%~dp0repeat_analyses.py" %*
if errorlevel 1 echo The check did not complete. Read the message above and README.txt.
pause
endlocal
