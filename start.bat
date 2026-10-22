@echo off
rem Double-click this file to start Hearth on Windows.
rem It needs Python 3.10 or newer (https://www.python.org/downloads/ , tick "Add python.exe to PATH").
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 ( set PY=py -3 ) else ( set PY=python )

%PY% --version >nul 2>nul
if errorlevel 1 (
  echo Python was not found. Please install Python 3.10 or newer from https://www.python.org/downloads/
  echo During install, tick "Add python.exe to PATH", then double-click this file again.
  pause
  exit /b 1
)

if not exist ".venv" (
  echo Setting up for the first time. This takes about a minute...
  %PY% -m venv .venv
)
call ".venv\Scripts\activate.bat"
pip install -q -r requirements.txt
if errorlevel 1 (
  echo Could not install the requirements. Check your internet connection and try again.
  pause
  exit /b 1
)

start "" cmd /c "timeout /t 3 >nul & start http://127.0.0.1:8765/"
python -m hearth.server
pause
