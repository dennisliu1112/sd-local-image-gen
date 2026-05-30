@echo off
title Z-Image Generator

:: Portable: use bundled Python, fall back to system Python
set "PYTHON=%~dp0python\python.exe"
if not exist "%PYTHON%" set "PYTHON=python"

:: Bundled dependencies live in python\Lib\site-packages (embeddable) or lib\
set "PYTHONPATH=%~dp0lib"

echo Starting Z-Image Generator...
echo.
echo  Open in browser: http://localhost:8080
echo  Press Ctrl+C to stop.
echo.
start "" "http://localhost:8080"
"%PYTHON%" "%~dp0server.py"
pause
