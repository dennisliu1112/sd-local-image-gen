@echo off
chcp 65001 >nul
title Z-Image Generator — 下載模型

set "MODELDIR=%~dp0models"
if not exist "%MODELDIR%" mkdir "%MODELDIR%"

set "PYDIR=%~dp0python"
if exist "%PYDIR%\python.exe" (set "PYTHON=%PYDIR%\python.exe") else (set "PYTHON=python")

echo.
echo ╔══════════════════════════════════════════╗
echo ║   Z-Image Generator — 模型下載           ║
echo ║   共約 6.3 GB，請確保硬碟空間充足        ║
echo ╚══════════════════════════════════════════╝
echo.

:: Download using Python's urllib (no extra dependencies)
"%PYTHON%" -c "
import urllib.request, sys, os
from pathlib import Path

models = [
    ('z_image_turbo-Q4_K.gguf', 'https://huggingface.co/shuttleai/shuttle-jaguar/resolve/main/z_image_turbo-Q4_K.gguf'),
    ('ae.safetensors',          'https://huggingface.co/black-forest-labs/FLUX.1-schnell/resolve/main/ae.safetensors'),
    ('Qwen3-4B-Q4_K_M.gguf',    'https://huggingface.co/Qwen/Qwen3-4B-GGUF/resolve/main/Qwen3-4B-Q4_K_M.gguf'),
]

dest = Path(sys.argv[1])

def progress(count, block, total):
    pct = min(100, count * block * 100 // total)
    mb = count * block // (1024*1024)
    total_mb = total // (1024*1024)
    print(f'\r  {pct:3d}%% [{mb}/{total_mb} MB]', end='', flush=True)

for fname, url in models:
    out = dest / fname
    if out.exists():
        print(f'[跳過] {fname} 已存在')
        continue
    print(f'[下載] {fname}')
    try:
        urllib.request.urlretrieve(url, str(out), reporthook=progress)
        print()
        print(f'  -> 完成')
    except Exception as e:
        print(f'\n  [錯誤] {e}')
        if out.exists(): out.unlink()

print()
print('所有模型下載完成！')
" "%MODELDIR%"

echo.
pause
