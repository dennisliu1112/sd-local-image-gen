# Building the Windows Desktop App

This documents how the **Amazing image Generator** Windows desktop app is
packaged, and why it's built the way it is. It covers the Electron shell +
embedded Python backend, distributed as an NSIS installer.

> For the API / MCP developer path, see the top-level [README.md](../README.md).
> This file is only about the packaged desktop app.

---

## TL;DR — how to build

**Locally (on Windows):**

```powershell
# from the repo root
.\build_windows.ps1
# → electron\release\Amazing image Generator-Setup-<version>.exe
```

**Via CI — two modes:**

- **Test build:** GitHub → Actions → *Build Windows App (Electron)* → **Run
  workflow**. The installer is uploaded as a 7-day build artifact (login
  required). Does *not* publish a Release.
- **Release for colleagues:** push a version tag — the workflow builds **and**
  publishes the installer to GitHub Releases automatically:

  ```bash
  git tag v1.1.0
  git push origin v1.1.0
  ```

  Because the repo is public, colleagues download the `.exe` straight from the
  [Releases page](https://github.com/dennisliu1112/sd-local-image-gen/releases)
  with no GitHub login.

Requirements: Node.js 20+ and internet access. **No Python install needed** —
the build downloads the official embeddable CPython package itself.

---

## Architecture

```
Electron shell (main.js)         ← window + lifecycle, spawns the backend
        ↓  spawn  python.exe server.py
Embedded Python + server.py      ← FastAPI backend (the "server")
        ↓  spawn  sd-server.exe
stable-diffusion.cpp engine      ← downloaded on first run, not bundled
```

The packaged layout splits **read-only app code** from **user data**:

```
C:\AiG\                               ← install dir (overwritten on update)
  Amazing image Generator.exe         ← Electron shell
  resources\
    python\     python.exe + Lib\site-packages\ (embedded CPython runtime)
    backend\    server.py + static\   (FastAPI backend + web UI)

C:\AiG-data\                          ← USER DATA (survives updates/uninstall)
  models\         ← downloaded on first run
  engine-cpu\     ← downloaded on first run (CUDA optional, opt-in)
  config.json     ← written at runtime
  logs\           ← written at runtime
```

The data dir is deliberately **outside** `C:\AiG` so app updates and reinstalls
never wipe the user's multi-GB models. The Electron shell passes its location
to the backend via the `AIG_DATA_DIR` env var (`server.py` resolves it, with
per-user app-data and the app dir as fallbacks); the installer creates
`C:\AiG-data` and grants it to `Users` so the non-elevated app can write there.
Model + engine downloads target this dir automatically (they are `ROOT`-relative).

---

## Why embedded Python instead of PyInstaller

The backend used to be packed into `server.exe` with PyInstaller. **Antivirus
(Windows Defender / SmartScreen) kept quarantining it.** PyInstaller's bootloader
self-extracts and loads code in memory — the same technique malware packers use —
and because the exe is unsigned, heuristic engines flag it almost every time.

The fix: **don't produce a packed exe at all.** We bundle the official Windows
*embeddable* CPython runtime (`python.exe`, signed by the Python Software
Foundation) plus the `server.py` source, and launch it with
`python.exe server.py`. There's no packer signature and no unsigned exe of our
own for AV to flag.

Build steps (see `build_windows.ps1` / `.github/workflows/build-windows.yml`):

1. Download `python-<ver>-embed-amd64.zip` from python.org.
2. Enable `import site` in `python*._pth` so pip-installed packages are importable.
3. Bootstrap pip (`get-pip.py`), then `pip install -r windows-app/requirements.txt`.
4. Bundle the result as `resources\python\`.

---

## Why a fixed `C:\AiG` install path

The app downloads its engine + model files into the install dir at runtime, and
the underlying `sd-server` uses a **narrow-char file API that breaks on non-ASCII
paths** (e.g. a `桌面` / `下載` folder). The old zip distribution let users
extract anywhere, so a Chinese-locale path could silently break image loading.

An NSIS installer pinned to `C:\AiG` removes that whole class of failure: the
path is guaranteed ASCII regardless of the user's locale or username.

Pinning + permissions are handled in [`build/installer.nsh`](build/installer.nsh):

- `preInit` writes `InstallLocation = C:\AiG` to the registry so electron-builder
  uses it as `$INSTDIR` (with `allowToChangeInstallationDirectory: false`).
- `customInstall` runs `icacls` to grant `BUILTIN\Users` **Modify** rights on
  `C:\AiG`, so the non-elevated app can write `models/`, `engine-*/`,
  `config.json` and `logs/` after the elevated install finishes.

The installer itself is unsigned, so SmartScreen shows a one-time "unknown
publisher" prompt — the user clicks *More info → Run anyway*. This is a warning,
not a deletion, and is unrelated to the (now-solved) Defender quarantine problem.

---

## Does this affect macOS?

- **macOS dev mode** (`npm start`, using `.venv`): **not affected.** The dev
  branch of `backendCmd()` in `main.js` is unchanged, and `server.py` is
  cross-platform.
- **macOS packaging** (`electron-builder --mac`): not automated by any CI. The
  Windows embedded runtime is scoped under `win.extraResources`, so a mac build
  won't pick it up. To package for mac later, add a `mac.extraResources` entry
  pointing at a macOS embedded Python (the packaged `backendCmd()` already looks
  for `resources/python/bin/python3` on non-Windows).
