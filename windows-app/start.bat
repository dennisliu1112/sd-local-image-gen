@echo off
chcp 65001 >nul
title Z-Image Generator

:: Use bundled Python if available, otherwise use system Python
set "PYDIR=%~dp0python"
if exist "%PYDIR%\python.exe" (
    set "PYTHON=%PYDIR%\python.exe"
    set "PIP=%PYDIR%\Scripts\pip.exe"
) else (
    set "PYTHON=python"
    set "PIP=pip"
)

:: Check models exist
if not exist "%~dp0models\z_image_turbo-Q4_K.gguf" (
    echo.
    echo [!] 找不到模型檔案。請先執行 download_models.bat 下載模型。
    echo.
    pause
    exit /b 1
)

:: Install dependencies
echo [1/2] 安裝依賴套件...
"%PYTHON%" -m pip install -q -r "%~dp0requirements.txt"

:: Start server
echo [2/2] 啟動伺服器...
echo.
echo  Z-Image Generator 已啟動！
echo  請在瀏覽器開啟：http://localhost:8080
echo.
echo  按 Ctrl+C 可停止伺服器。
echo.
start "" "http://localhost:8080"
"%PYTHON%" "%~dp0server.py"
pause
