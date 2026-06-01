# Build the Windows app locally (embedded Python + NSIS installer).
# Mirrors .github/workflows/build-windows.yml so you can build on your own
# machine without pushing to CI.
#
# Usage (from the repo root, in PowerShell):
#   .\build_windows.ps1
#
# Output: electron\release\Amazing image Generator-Setup-<version>.exe
#
# Requirements: Node.js 20+, internet access. No Python install needed — we
# download the official embeddable CPython package.

$ErrorActionPreference = 'Stop'
$PyEmbedVersion = '3.12.7'

# Resolve repo root = this script's directory, regardless of where it's run.
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

Write-Host "==> Building embedded Python runtime ($PyEmbedVersion)" -ForegroundColor Cyan

# Clean any previous runtime so deps don't accumulate stale versions.
if (Test-Path runtime) { Remove-Item runtime -Recurse -Force }

$url = "https://www.python.org/ftp/python/$PyEmbedVersion/python-$PyEmbedVersion-embed-amd64.zip"
Write-Host "    Downloading $url"
Invoke-WebRequest -Uri $url -OutFile pyembed.zip
Expand-Archive -Path pyembed.zip -DestinationPath runtime -Force
Remove-Item pyembed.zip

# Enable site-packages so pip-installed deps are importable from the embeddable.
$pth = Get-ChildItem runtime -Filter "python*._pth" | Select-Object -First 1
(Get-Content $pth.FullName) `
  -replace '^\s*#\s*import site', 'import site' `
  | Set-Content $pth.FullName

Write-Host "==> Bootstrapping pip + installing backend deps" -ForegroundColor Cyan
Invoke-WebRequest -Uri "https://bootstrap.pypa.io/get-pip.py" -OutFile get-pip.py
runtime\python.exe get-pip.py --no-warn-script-location
runtime\python.exe -m pip install --no-warn-script-location -r windows-app\requirements.txt
Remove-Item get-pip.py -ErrorAction SilentlyContinue

# Trim cruft to keep the bundle lean.
Get-ChildItem runtime -Recurse -Directory -Filter "__pycache__" |
  Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

Write-Host "==> Smoke test (import backend deps)" -ForegroundColor Cyan
runtime\python.exe -c "import fastapi, uvicorn, httpx, PIL; print('deps OK')"

Write-Host "==> Installing Electron deps + building NSIS installer" -ForegroundColor Cyan
Push-Location electron
try {
  if (Test-Path node_modules) {
    npm install
  } else {
    npm ci
  }
  npx electron-builder --win nsis --x64 --publish never
}
finally {
  Pop-Location
}

Write-Host "`n==> Done. Installer is in electron\release\" -ForegroundColor Green
Get-ChildItem electron\release\*.exe -ErrorAction SilentlyContinue |
  Select-Object Name, @{N='Size(MB)';E={[math]::Round($_.Length/1MB,1)}}
