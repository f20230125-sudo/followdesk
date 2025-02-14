@echo off
setlocal
cd /d "%~dp0"
set "TEMP=%~dp0.local\temp"
set "TMP=%TEMP%"
set "PIP_CACHE_DIR=%~dp0.local\pip-cache"
set "PYTHONPYCACHEPREFIX=%~dp0.local\pycache"
if not exist "%TEMP%" mkdir "%TEMP%"
if not exist ".venv\Scripts\python.exe" py -3.14 -m venv .venv
if not exist ".venv\Scripts\python.exe" exit /b 1
.venv\Scripts\python.exe -m pip install --no-index --find-links .local\wheels -r requirements.txt
if errorlevel 1 exit /b 1
.venv\Scripts\python.exe scripts\manage.py run
