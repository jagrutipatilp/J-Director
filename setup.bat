@echo off
setlocal
cd /d "%~dp0"
echo ============================================================
echo   KupkaProd Cinema Pipeline - Setup
echo   Powered by LTX 2.3
echo ============================================================
echo.
echo Installing Python dependencies...
echo.
if not exist ".venv\Scripts\python.exe" (
    where py >nul 2>nul
    if errorlevel 1 (
        python -m venv .venv
    ) else (
        py -3 -m venv .venv
    )
)
if not exist ".venv\Scripts\python.exe" (
    echo Python 3.10 or newer is required to create the environment.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -m pip install -r requirements.txt
echo.
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Failed to install dependencies. Make sure Python and pip are on your PATH.
    echo.
    pause
    exit /b 1
)
echo.
echo ============================================================
echo   Setup complete!
echo.
echo   Next steps:
echo     1. Make sure ComfyUI is installed and working
echo     2. Make sure Ollama is installed: https://ollama.ai
echo     3. Pull the recommended model: ollama pull gemma4:e4b
echo     4. Run start.bat to launch the application
echo ============================================================
echo.
pause
