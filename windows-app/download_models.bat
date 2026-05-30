@echo off
title Z-Image Generator - Download Models

set "MODELDIR=%~dp0models"
if not exist "%MODELDIR%" mkdir "%MODELDIR%"

set "PYDIR=%~dp0python"
if exist "%PYDIR%\python.exe" (set "PYTHON=%PYDIR%\python.exe") else (set "PYTHON=python")

echo.
echo Z-Image Generator - Model Download
echo Total size: ~6.3 GB
echo.

"%PYTHON%" -c "
import urllib.request, sys
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
        print(f'[skip] {fname} already exists')
        continue
    print(f'[download] {fname}')
    try:
        urllib.request.urlretrieve(url, str(out), reporthook=progress)
        print()
    except Exception as e:
        print(f'  [error] {e}')
        if out.exists(): out.unlink()

print('Done.')
" "%MODELDIR%"

echo.
pause
