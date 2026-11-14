@echo off
setlocal
cd /d "%~dp0"
set "PATH=%~dp0tools\ollama;%~dp0tools\ffmpeg;%PATH%"
set "OLLAMA_MODELS=%~dp0local-models\ollama"
if not exist ".venv\Scripts\python.exe" (
    echo Run setup.bat to install Python dependencies first.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -u download_local_models.py
if errorlevel 1 goto failed
if not exist "tools\ffmpeg\ffprobe.exe" (
    ".venv\Scripts\python.exe" install_ffmpeg.py
    if errorlevel 1 goto failed
)
".venv\Scripts\python.exe" configure_local.py
if errorlevel 1 goto failed
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-services.ps1"
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -u pull_planning_model.py
if errorlevel 1 goto failed
".venv\Scripts\python.exe" verify_local_setup.py
if errorlevel 1 goto failed
echo Setup checks passed. Run start.bat to open KupkaProd.
pause
exit /b 0
:failed
echo Setup stopped. Run this file again to resume saved downloads.
pause
exit /b 1
