@echo off
REM ============================================================
REM  SupportSphere AI - one-click start for Windows
REM  Double-click this file. The first run installs everything.
REM ============================================================
cd /d "%~dp0"
title SupportSphere AI

set PY=
where python >nul 2>nul && set PY=python
if "%PY%"=="" where py >nul 2>nul && set PY=py
if "%PY%"=="" (
  echo.
  echo  Python was not found.
  echo  Install Python 3.9 or newer from https://www.python.org/downloads/
  echo  and tick "Add python.exe to PATH" during setup. Then run this file again.
  echo.
  pause
  exit /b 1
)

if not exist venv (
  echo Creating virtual environment ^(first run only^)...
  %PY% -m venv venv
  if errorlevel 1 ( echo Could not create the virtual environment. & pause & exit /b 1 )
)
call venv\Scripts\activate.bat

echo Checking packages...
python -m pip install -q -r requirements.txt
if errorlevel 1 (
  echo.
  echo  Package installation failed. Check your internet connection and try again.
  pause
  exit /b 1
)

echo.
echo  Starting SupportSphere AI at http://127.0.0.1:5000
echo  Keep this window open while you use the app. Press Ctrl+C to stop.
echo.
start "" http://127.0.0.1:5000
python app.py
pause
