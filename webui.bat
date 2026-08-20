@echo off
cd /d "%~dp0"
echo ============================================
echo  AI-Agent webui backend (debug mode)
echo  The backend will print its URL below.
echo  Press Ctrl+C to stop.
echo ============================================
.venv\Scripts\python webui.py
echo.
echo Backend exited. Fix errors shown above and retry.
pause
