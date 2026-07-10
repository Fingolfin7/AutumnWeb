@echo off
setlocal

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Could not find .venv\Scripts\python.exe
    echo Create the virtual environment and install the project dependencies first.
    pause
    exit /b 1
)

echo Starting AutumnWeb at http://localhost:8000/
echo Press Ctrl+C to stop the server.
echo.

".venv\Scripts\python.exe" manage.py runserver 127.0.0.1:8000

if errorlevel 1 (
    echo.
    echo The development server stopped with an error.
    pause
)

endlocal
