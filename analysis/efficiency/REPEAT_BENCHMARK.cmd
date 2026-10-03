@echo off
setlocal
cd /d "%~dp0"
set "BENCHPY=%~dp0..\..\runtime\python.exe"
if exist "%BENCHPY%" goto run
set "BENCHPY=%~dp0.benchmark-venv\Scripts\python.exe"
if exist "%BENCHPY%" goto run
py -3.13 -m venv "%~dp0.benchmark-venv"
if errorlevel 1 goto failed
"%BENCHPY%" -m pip install -r "%~dp0requirements.txt"
if errorlevel 1 goto failed
:run
set "BENCHOUT=%~dp0results-%RANDOM%-%RANDOM%"
"%BENCHPY%" "%~dp0reproduce_benchmark.py" --output "%BENCHOUT%"
if errorlevel 1 goto failed
start "" "%BENCHOUT%\REPORT.html"
pause
exit /b 0
:failed
echo The comparison did not finish successfully. Read the message above.
pause
exit /b 1
