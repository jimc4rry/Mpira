@echo off
REM ============================================================
REM  Mpira - one-click local run (Windows)
REM  - creates .venv and installs requirements (only when they change)
REM  - creates .env from .env.example on first run
REM  - applies migrations and loads the demo data (once)
REM  - starts the dev server and opens the browser
REM
REM  Usage:  run.bat          -> http://127.0.0.1:8000
REM          run.bat lan      -> also reachable from other PCs on your network
REM          run.bat reset    -> wipe the local SQLite DB and re-seed demo data
REM ============================================================
setlocal
cd /d "%~dp0"

set "PY=.venv\Scripts\python.exe"

if not exist "%PY%" (
    echo [Mpira] Creating virtual environment...
    py -3.11 -m venv .venv 2>nul || python -m venv .venv
    if not exist "%PY%" (
        echo [Mpira] Could not create the virtual environment. Is Python 3.11+ installed?
        pause
        exit /b 1
    )
)

fc /b requirements.txt .venv\requirements.installed >nul 2>nul
if errorlevel 1 (
    echo [Mpira] Installing dependencies...
    "%PY%" -m pip install -q --upgrade pip
    "%PY%" -m pip install -q -r requirements-dev.txt || (echo [Mpira] pip install failed & pause & exit /b 1)
    copy /y requirements.txt .venv\requirements.installed >nul
)

if not exist ".env" (
    echo [Mpira] Creating .env from .env.example
    copy .env.example .env >nul
)

if /i "%1"=="reset" (
    echo [Mpira] Resetting the local database...
    if exist db.sqlite3 del /q db.sqlite3
)

echo [Mpira] Applying migrations...
"%PY%" manage.py migrate --noinput || (pause & exit /b 1)

echo [Mpira] Loading demo data (skipped if it already exists)...
"%PY%" manage.py seed_demo

set "ADDR=127.0.0.1:8000"
if /i "%1"=="lan" set "ADDR=0.0.0.0:8000"

echo.
echo  ==========================================================
echo   Mpira is starting on http://127.0.0.1:8000
echo   Demo logins (password: see DEMO_PASSWORD in .env):
echo     admin@mpira.local   - Admin
echo     maria@mpira.local   - Project Manager
echo     nikos@mpira.local   - Developer
echo     eleni@mpira.local   - Tester
echo   Press Ctrl+C to stop.
echo  ==========================================================
echo.

if not defined MPIRA_NO_BROWSER start "" http://127.0.0.1:8000
"%PY%" manage.py runserver %ADDR%
endlocal
