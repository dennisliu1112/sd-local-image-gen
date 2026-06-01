#!/usr/bin/env bash
# Build the macOS app locally (relocatable CPython + Metal sd-server + .dmg).
# Mirrors build_windows.ps1 for the Mac side. Run on an Apple Silicon Mac.
#
# Usage (from the repo root):
#   ./build_macos.sh
#
# Output: electron/release/Amazing image Generator-<version>-mac-arm64.dmg
#
# Requirements: macOS arm64, Node 20+, internet access, and a built Metal
# sd-server at src/build/bin/sd-server. No system Python needed — we fetch a
# relocatable CPython from python-build-standalone (the same approach the
# Windows build uses with the official embeddable package).
set -euo pipefail

# python-build-standalone: there is no official relocatable mac CPython, so we
# use astral's standalone build. Pinned to match the Windows embeddable 3.12.7.
PY_TAG='20241016'
PY_VER='3.12.7'
PY_URL="https://github.com/astral-sh/python-build-standalone/releases/download/${PY_TAG}/cpython-${PY_VER}+${PY_TAG}-aarch64-apple-darwin-install_only.tar.gz"
ENGINE_SRC='src/build/bin/sd-server'

cd "$(dirname "$0")"
ROOT="$(pwd)"

echo "==> Preparing relocatable Python runtime ($PY_VER)"
rm -rf runtime-mac
mkdir -p runtime-mac
echo "    Downloading $PY_URL"
curl -fL "$PY_URL" -o /tmp/pystandalone.tar.gz
# install_only tarball has a top-level python/ dir; strip it so runtime-mac/
# directly holds bin/, lib/, … (matches main.js's resources/python/bin/python3).
tar -xzf /tmp/pystandalone.tar.gz -C runtime-mac --strip-components=1
rm -f /tmp/pystandalone.tar.gz

echo "==> Installing backend deps into the runtime"
runtime-mac/bin/python3 -m pip install --upgrade pip >/dev/null
runtime-mac/bin/python3 -m pip install -r windows-app/requirements.txt

echo "==> Trimming runtime cruft"
find runtime-mac -type d -name "__pycache__" -prune -exec rm -rf {} + 2>/dev/null || true
find runtime-mac -type d -name "test" -path "*/lib/*" -prune -exec rm -rf {} + 2>/dev/null || true

echo "==> Smoke test (import backend deps from the bundled runtime)"
runtime-mac/bin/python3 -c "import fastapi, uvicorn, httpx, PIL; print('deps OK')"

echo "==> Staging the Metal sd-server engine"
if [ ! -f "$ENGINE_SRC" ]; then
  echo "ERROR: $ENGINE_SRC not found. Build it first:" >&2
  echo "  cd src/stable-diffusion.cpp && cmake -B build -DSD_METAL=ON -DCMAKE_BUILD_TYPE=Release && cmake --build build -j" >&2
  exit 1
fi
rm -rf mac-engine
mkdir -p mac-engine
cp "$ENGINE_SRC" mac-engine/sd-server
chmod +x mac-engine/sd-server
# Ensure it carries (at least) an ad-hoc signature so macOS will exec it.
codesign --force --sign - mac-engine/sd-server 2>/dev/null || true

echo "==> Installing Electron deps + building the .dmg"
cd electron
if [ -d node_modules ]; then npm install; else npm ci; fi
npx electron-builder --mac dmg --arm64 --publish never
cd "$ROOT"

echo
echo "==> Done. DMG is in electron/release/"
ls -lh electron/release/*.dmg 2>/dev/null || true
