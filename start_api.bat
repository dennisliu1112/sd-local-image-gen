@echo off
:: Start the Stable Diffusion API server in background
:: Usage: start_api.bat [port]
set PORT=%1
if "%PORT%"=="" set PORT=8080

set ROOT=%~dp0
cd /d "%ROOT%"

echo Checking Python dependencies...
pip install -q -r requirements_api.txt

echo.
echo Starting SD API server on http://localhost:%PORT%
echo Docs available at http://localhost:%PORT%/docs
echo Press Ctrl+C to stop.
echo.

set SD_API_PORT=%PORT%
python sd_api.py
