@echo off
:: Start the SD API server as a detached background process (new window)
set PORT=%1
if "%PORT%"=="" set PORT=8080

set ROOT=%~dp0
cd /d "%ROOT%"

echo Installing dependencies...
pip install -q -r requirements_api.txt

echo Starting SD API server in background on port %PORT%...
start "SD-API" /min cmd /c "python sd_api.py >> logs\sd_api_stdout.log 2>&1"

echo.
echo Server started. Check logs\sd_api.log for output.
echo API: http://localhost:%PORT%
echo Docs: http://localhost:%PORT%/docs
echo.
echo To stop: find and close the "SD-API" window, or:
echo   taskkill /FI "WINDOWTITLE eq SD-API" /F
