# macOS Build — ship a `.dmg` alongside the Windows `.exe`

> ✅ **DONE as of v1.1.1.** The mac `.dmg` builds with [`build_macos.sh`](../build_macos.sh)
> and is released alongside the Windows `.exe`. This doc is kept as the design
> record + how-to. The `.dmg` **must be built on macOS** (electron-builder can't
> produce a mac app on Windows).
>
> Companion docs: [BUILD_WINDOWS.md](BUILD_WINDOWS.md) (Windows pipeline).

## How to build the mac dmg

```bash
./build_macos.sh        # from the repo root, on an Apple Silicon Mac
# → electron/release/Amazing image Generator-<version>-mac-arm64.dmg
```

It fetches a relocatable CPython (python-build-standalone, pinned to match the
Windows 3.12.7), installs the backend deps into it, bundles the Metal
`sd-server` engine, and runs electron-builder. Prereq: the Metal engine exists
at `src/build/bin/sd-server` (see "Engine" below).

## Status (shipped in v1.1.1)

- ✅ **Windows**: NSIS installer → `C:\AiG`, embedded CPython backend (no
  PyInstaller), engine auto-selects CPU (never Vulkan — Z-Image renders blank on
  it, sd.cpp#1031), user data in `C:\AiG-data`. Built by CI on tag push.
- ✅ **macOS (arm64)**: `.dmg`, relocatable CPython + **bundled** Metal
  `sd-server` (no download path on mac), user data in
  `~/Library/Application Support/Amazing image Generator/data`. Z-Image **renders
  correctly on Metal** (verified end-to-end). Built locally with
  `build_macos.sh`, uploaded to the same GitHub Release as the `.exe`.

### Gatekeeper note for users (unsigned build)

The `.dmg` is **not signed/notarized** ($99 Apple Developer Program). On first
launch macOS shows "unidentified developer". Workarounds:

- Right-click the app → **Open** → **Open** (once), or
- `xattr -dr com.apple.quarantine "/Applications/Amazing image Generator.app"`

The bundled `sd-server` and CPython binaries are already ad-hoc signed, so they
exec fine once the app itself is allowed.

## Why most of the port is cheap

Electron is cross-platform and `main.js` already has the mac branches; the
coupling audit below found **no architectural blockers** — only engine delivery
and packaging config need mac work.

## Coupling audit

### 🟢 Already cross-platform — no work needed
- `main.js`: `backendCmd()` (else → `python/bin/python3`), `dataDir()` (else →
  `app.getPath('userData')/data`), menu (`isMac`), `stopBackend` (tree-kill).
- `server.py`: `EXE_NAME` (non-nt → no `.exe`), `_build_cmd` (darwin →
  `--vae-on-cpu`; nt-only → `--offload-to-cpu`), `_kill_port` (nt vs lsof/kill),
  `_pid_alive`, `_watch_parent`, `open_output` (darwin/nt/else),
  `_resolve_data_dir`, `_short_path` (no-op on non-nt).

### 🔴 Must fix for mac — engine delivery (3 coupled spots, all Windows-only)
- `server.py` `download_engine()` — returns an error on non-Windows.
- `server.py` `ENGINE_ZIPS` — Windows-only download URLs (vulkan/cpu/cuda win).
- `server.py` `_download_engines()` — extracts only `.exe`/`.dll`; a mac engine
  is `sd-server` (no extension) + `.dylib`, so even with mac URLs this grabs
  nothing.
- **Recommended fix: BUNDLE the mac `sd-server` in `mac.extraResources`** →
  bypasses the whole download path. Those 3 spots stay Windows-only and unused
  on mac; no download logic to rewrite (lowest coupling risk).

### 🔴 Must fix for mac — packaging
- `package.json`: add `mac.target` = `dmg` and `mac.extraResources` (the mac
  Python runtime + the bundled mac engine). The `mac` block currently only sets
  the icon.

### ⚪ Windows-only by design — needs a mac counterpart file
- `build/installer.nsh` (NSIS) → not needed on mac (dmg).
- `build_windows.ps1` → write `build_macos.sh`.
- `.github/workflows/build-windows.yml` → add a `macos-latest` job (below).

## Work items (do these on the Mac)

1. **Engine**: locate the existing mac `sd-server` (Mach-O, Metal). If gone,
   rebuild from stable-diffusion.cpp source: `cmake -B build -DSD_METAL=ON
   -DCMAKE_BUILD_TYPE=Release`. Note the arch (arm64 vs universal).
2. **Embedded Python (mac)**: there is **no official mac embeddable** zip — use
   [python-build-standalone](https://github.com/astral-sh/python-build-standalone)
   (relocatable CPython). Install `windows-app/requirements.txt` into it. Bundle
   as `resources/python`; `backendCmd()` already expects
   `resources/python/bin/python3`.
3. **`build_macos.sh`**: mirror `build_windows.ps1` — fetch/prepare the mac
   Python runtime, then `npx electron-builder --mac dmg --publish never`.
4. **`package.json`**: add `mac.target: dmg` + `mac.extraResources` (python +
   engine).
5. **Test locally**: install the `.dmg`, first run, generate an image (engine
   should resolve to cpu/metal), confirm data dir lands in
   `~/Library/Application Support/<app>/data`.
6. **Gatekeeper** (the mac "trust window", = Windows SmartScreen): an unsigned
   `.dmg` is blocked ("unidentified developer"). Workaround: right-click → Open.
   Proper fix: Apple Developer ID cert + **notarization** (Apple Developer
   Program, $99/yr). Optional — same $99 program as any future iOS work.

## CI: one Release, both `.exe` + `.dmg` (three-job pattern)

A single GitHub Release holds multiple assets; users pick their OS. Restructure
the workflow into three jobs so the two platform builds publish atomically to
one release (avoids the race of two jobs creating the same release):

```yaml
jobs:
  build-windows:   # windows-latest → .exe → upload-artifact
  build-macos:     # macos-latest   → .dmg → upload-artifact
  release:
    needs: [build-windows, build-macos]
    if: startsWith(github.ref, 'refs/tags/')
    runs-on: ubuntu-latest
    steps:
      - uses: actions/download-artifact@v4   # collect .exe + .dmg
      - uses: softprops/action-gh-release@v2
        with:
          files: dist/**/*                   # both onto the same tag
          fail_on_unmatched_files: true
          generate_release_notes: true
```

⚠️ **Do not restructure the CI until `build-macos` actually works** — adding a
broken/missing mac job to `needs:` would block the currently-working Windows
release.

## De-risk before building the app (if Z-Image on Metal is uncertain)

Z-Image was blank on **Vulkan** (sd.cpp#1031). **Metal** is a different backend
and may hit different unimplemented-op bugs (e.g. #1040). On an Apple Silicon
Mac, build the Metal engine and confirm Z-Image renders a correct image before
trusting it on mac/iOS. If it fails, the app still works with a Metal-proven
turbo model (SDXL-Turbo / SD-Turbo).

## Parked: iPad on-device (Route B)

Dropped for now. If resumed: target = M4 iPad Pro **8 GB** (lowest tier). Needs
**staged model loading** (load LLM → encode → free → load diffusion; peak ≈
`max(2.4 GB, 3.7+0.3 GB) ≈ 4 GB`) + `increased-memory-limit` entitlement. The
naive "load all 6.4 GB at once" will not fit in 8 GB. Verify Z-Image-on-Metal
correctness first (same risk as above). ggml uses the **GPU (Metal)**, not the
Neural Engine; ANE would require the Core ML route, which doesn't support
Z-Image.
