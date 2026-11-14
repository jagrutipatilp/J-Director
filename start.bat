@echo off
setlocal
cd /d "%~dp0"
set "PATH=%~dp0tools\ollama;%~dp0tools\ffmpeg;%PATH%"
set "OLLAMA_MODELS=%~dp0local-models\ollama"
set "OLLAMA_HOST=127.0.0.1:11434"
set "OLLAMA_MAX_LOADED_MODELS=1"
set "OLLAMA_NUM_PARALLEL=1"
set "OLLAMA_KEEP_ALIVE=0"
echo ============================================================
echo   KupkaProd Cinema Pipeline
echo   Powered by LTX 2.3
echo ============================================================
echo.
echo Starting application...
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-services.ps1"
if errorlevel 1 (
    pause
    exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
    echo Please run setup.bat first.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" video_director_agent/gui.py
echo.
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Application exited with an error.
    echo   Make sure you ran setup.bat first.
    echo   Make sure Python is on your PATH.
    echo.
)
echo.
echo Application closed.
pause
