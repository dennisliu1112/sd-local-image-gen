@echo off
:: Build sd-server from source (Windows + CUDA)
:: -----------------------------------------------
:: 1. Copy this file to build_sd.bat
:: 2. Adjust the paths below to match your environment
:: 3. Run build_sd.bat
::
:: Requirements:
::   - Visual Studio 2022 Build Tools (with MSVC + CMake + Ninja)
::   - CUDA Toolkit 12.x
::   - stable-diffusion.cpp source in src\
::     (git clone https://github.com/leejet/stable-diffusion.cpp src)

:: -----------------------------------------------
:: Adjust these paths to match your installation
:: -----------------------------------------------
set VSTOOLS=C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat
set NINJA=C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\Common7\IDE\CommonExtensions\Microsoft\CMake\Ninja\ninja.exe
set CMAKE=C:\Program Files\CMake\bin\cmake.exe
set CUDA_PATH=C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.6

:: -----------------------------------------------
:: Build
:: -----------------------------------------------
call "%VSTOOLS%"
cd /d %~dp0src

"%CMAKE%" -B build -G Ninja ^
  -DGGML_CUDA=ON ^
  -DCMAKE_BUILD_TYPE=Release ^
  -DCUDAToolkit_ROOT="%CUDA_PATH%" ^
  -DCMAKE_CUDA_COMPILER="%CUDA_PATH%\bin\nvcc.exe" ^
  -DCMAKE_MAKE_PROGRAM="%NINJA%"

"%NINJA%" -C build

echo.
echo Done. Copy build\bin\sd-server.exe and CUDA DLLs to ..\src\build\bin\
