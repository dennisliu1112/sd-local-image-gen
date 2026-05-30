@echo off
title Z-Image Generator

:: Portable: use bundled Python, fall back to system Python
set "PYTHON=%~dp0python\python.exe"
if not exist "%PYTHON%" set "PYTHON=python"

:: Bundled dependencies live in python\Lib\site-packages (embeddable) or lib\
set "PYTHONPATH=%~dp0lib"

echo Starting Z-Image Generator...
echo.
echo  The browser will open automatically once the server is ready.
echo  (Model loading takes ~15-60 seconds on first launch.)
echo  Press Ctrl+C in this window to stop.
echo.

:: Background waiter: open browser only after the server responds
start "" powershell -NoProfile -WindowStyle Hidden -Command ^
  "do { Start-Sleep -Milliseconds 800; try { $r = Invoke-WebRequest 'http://localhost:8080/health' -UseBasicParsing -TimeoutSec 2 } catch {} } until ($r.StatusCode -eq 200); Start-Process 'http://localhost:8080'"

:: Run server in foreground (Ctrl+C stops it)
"%PYTHON%" "%~dp0server.py"
pause
