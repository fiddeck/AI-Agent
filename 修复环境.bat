@echo off
setlocal
cd /d "%~dp0"
echo ============================================
echo   AI-Agent environment repair
echo   This deletes the OLD .venv (which is bound
echo   to the source PC's Python path) and creates
echo   a fresh one with THIS computer's Python.
echo ============================================
echo.

if exist ".venv" (
    echo [1/4] Removing old .venv ...
    rmdir /s /q ".venv"
    if exist ".venv" (
        echo ERROR: failed to delete .venv - is the app still running?
        pause
        exit /b 1
    )
) else (
    echo [1/4] No old .venv found, skipping.
)

echo [2/4] Looking for uv ...
where uv >nul 2>nul
if %errorlevel%==0 (
    echo       uv found - running "uv sync" ...
    uv sync
    if errorlevel 1 (
        echo ERROR: uv sync failed. Check network / Python 3.13 install.
        pause
        exit /b 1
    )
) else (
    echo       uv not found - falling back to python -m venv + pip
    where python >nul 2>nul
    if errorlevel 1 (
        echo ERROR: no "python" on PATH. Install Python 3.13 first, then rerun.
        pause
        exit /b 1
    )
    echo [3/4] Creating venv with python -m venv .venv ...
    python -m venv .venv
    if errorlevel 1 (
        echo ERROR: venv creation failed.
        pause
        exit /b 1
    )
    echo [4/4] Installing dependencies from pyproject.toml ...
    .venv\Scripts\python.exe -m pip install --upgrade pip
    .venv\Scripts\python.exe -m pip install -e . -i https://pypi.tuna.tsinghua.edu.cn/simple
    if errorlevel 1 (
        echo ERROR: pip install failed.
        pause
        exit /b 1
    )
)

echo.
echo Verifying key packages ...
.venv\Scripts\python.exe -c "import fastapi, uvicorn, websockets, mcp, openai; print('ALL OK')"
if errorlevel 1 (
    echo WARNING: a package import failed - see message above.
    pause
    exit /b 1
)

echo.
echo ============================================
echo   Done! Next steps:
echo     1. Set your API key (once):
echo          setx OPENAI_API_KEY "sk-xxxx"
echo        then restart the app / reopen a terminal.
echo     2. Launch: double-click the AI-Agent
echo        desktop shortcut, or run webui.bat.
echo ============================================
pause
