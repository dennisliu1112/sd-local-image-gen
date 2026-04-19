@echo off
:: ============================================================
:: run_test.bat — Quick test: does image generation work?
:: ============================================================
::
:: This script calls the AI engine (sd-cli.exe) DIRECTLY to
:: generate one test image. It does NOT go through the API
:: server — use this to verify your binary and models are
:: working before starting the full API stack.
::
:: What you need before running:
::   1. sd-cli.exe + CUDA DLLs in src\build\bin\
::   2. Models downloaded to models\
::      (see README.md → Download Models)
::
:: Output: eval\local_test.png
:: Log:    test_out.txt
:: ============================================================

set ROOT=%~dp0
set EXE="%ROOT%src\build\bin\sd-cli.exe"
set DIFF="%ROOT%models\z_image_turbo-Q4_K.gguf"
set VAE="%ROOT%models\ae.safetensors"
set LLM="%ROOT%models\Qwen3-4B-Q4_K_M.gguf"
set OUT="%ROOT%eval"
set LOG="%ROOT%test_out.txt"

echo Generating test image...
echo This takes 20-40 minutes. Please wait.
echo.

echo START: %date% %time% > %LOG%
%EXE% ^
  --diffusion-model %DIFF% --vae %VAE% --llm %LLM% ^
  --vae-tiling --offload-to-cpu ^
  -p "1girl, masterpiece, 8k, photorealistic, beach, golden hour, cinematic lighting" ^
  --steps 4 --cfg-scale 1.0 -W 1024 -H 1024 ^
  -o %OUT%\local_test.png ^
  >> %LOG% 2>&1
echo END: %date% %time% >> %LOG%
echo EXIT_CODE=%ERRORLEVEL% >> %LOG%

echo.
echo Done! Check eval\local_test.png for the result.
echo If no image appeared, check test_out.txt for errors.
