@echo off
title Z-Image Generator

set "PYDIR=%~dp0python"
if exist "%PYDIR%\python.exe" (
    set "PYTHON=%PYDIR%\python.exe"
) else (
    set "PYTHON=python"
)

if not exist "%~dp0models\z_image_turbo-Q4_K.gguf" (
    echo.
    echo [!] Models not found. Please run download_models.bat first.
    echo.
    pause
    exit /b 1
)

echo [1/2] Installing dependencies...
"%PYTHON%" -m pip install -q -r "%~dp0requirements.txt"

echo [2/2] Starting server...
echo.
echo  Z-Image Generator is running at: http://localhost:8080
echo  Press Ctrl+C to stop.
echo.
start "" "http://localhost:8080"
"%PYTHON%" "%~dp0server.py"
pause
