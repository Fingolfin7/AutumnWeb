@echo off
setlocal

cd /d "%~dp0"

set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" (
    echo Could not find .venv\Scripts\python.exe
    echo Create the virtual environment and install the project dependencies first.
    pause
    exit /b 1
)

rem The web app: rebuild it so it matches the checked-out code.
where npm >nul 2>nul
if errorlevel 1 goto no_node
if not exist "frontend\node_modules" (
    echo Installing the web app's packages...
    pushd frontend
    call npm ci --no-audit --no-fund
    popd
)
echo Building the web app...
pushd frontend
call npm run build --silent >nul
set "BUILD_FAILED=%ERRORLEVEL%"
popd
if not "%BUILD_FAILED%"=="0" (
    echo The web app failed to build. Run "npm run build" in frontend\ to see why.
    pause
    exit /b 1
)
goto built

:no_node
if not exist "core\static\app\manifest.json" (
    echo The web app is not built and Node.js was not found.
    echo Install Node 22, then run "npm ci" and "npm run build" in frontend\.
    pause
    exit /b 1
)
echo Node.js was not found; using the web app as last built.

:built
rem With DEBUG off the server only serves collected static files.
"%PY%" manage.py collectstatic --noinput >nul
if errorlevel 1 (
    echo collectstatic failed.
    pause
    exit /b 1
)

"%PY%" manage.py migrate --check >nul 2>nul
if not errorlevel 1 goto migrated
echo.
echo The database has unapplied migrations:
"%PY%" manage.py showmigrations --plan 2>nul | findstr /C:"[ ]"
choice /C YN /M "Back up the database and apply them now"
if errorlevel 2 (
    echo Not migrating. The app may fail until you run: %PY% manage.py migrate
    goto migrated
)
"%PY%" scripts\backup_sqlite.py
if errorlevel 1 (
    echo The backup failed, so the migrations were not applied.
    pause
    exit /b 1
)
"%PY%" manage.py migrate
if errorlevel 1 (
    pause
    exit /b 1
)

:migrated
echo.
echo Starting AutumnWeb at http://127.0.0.1:8000/
echo Press Ctrl+C to stop the server.
echo.

"%PY%" manage.py runserver 127.0.0.1:8000

if errorlevel 1 (
    echo.
    echo The development server stopped with an error.
    pause
)

endlocal
