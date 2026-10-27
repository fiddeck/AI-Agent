@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [AI-Agent] .venv not found.
    echo Run the environment repair script first ^(it recreates .venv^).
    pause
    exit /b 1
)

".venv\Scripts\python.exe" chat.py
echo.
pause
