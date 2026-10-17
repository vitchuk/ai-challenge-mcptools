@echo off
cd /d "%~dp0"

REM Файл запуска приложения

if not exist ".venv\Scripts\python.exe" (
  echo Virtualenv not found: .venv\Scripts\python.exe
  echo Create it and install dependencies:
  echo   py -3 -m venv .venv
  echo   .venv\Scripts\python.exe -m pip install -r server\requirements.txt
  pause
  exit /b 1
)

".venv\Scripts\python.exe" "scripts\dev.py"
pause
