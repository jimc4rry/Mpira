@echo off
REM Runs the same checks as CI: system checks, missing migrations, test suite.
setlocal
cd /d "%~dp0"
set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" (
    echo Run run.bat once first to create the virtual environment.
    pause
    exit /b 1
)
"%PY%" manage.py check || goto :fail
"%PY%" manage.py makemigrations --check --dry-run || goto :fail
"%PY%" manage.py test %* || goto :fail
echo.
echo All checks passed.
pause
exit /b 0
:fail
echo.
echo Something failed - see above.
pause
exit /b 1
