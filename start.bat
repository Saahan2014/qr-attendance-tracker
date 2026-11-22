@echo off
cd /d "%~dp0"
where py >nul 2>nul && (set PY=py) || (set PY=python)
%PY% --version || (echo Python is not installed. Get it from python.org and tick "Add Python to PATH". & pause & exit /b)
%PY% -m pip install -q -r requirements.txt || (echo Installing the libraries failed. & pause & exit /b)
%PY% local_server.py
pause
