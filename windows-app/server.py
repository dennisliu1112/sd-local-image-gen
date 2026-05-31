"""
Z-Image Generator — Local Image Generation Server
Manages sd-server and exposes REST API + static UI.

Endpoints:
  POST /generate          - Submit generation job
  GET  /jobs/{id}         - Job status
  GET  /jobs              - List all jobs
  GET  /images/{id}       - Download generated image
  DELETE /jobs/{id}       - Remove job
  GET  /health            - Health check
  GET  /                  - Web UI
"""

import base64
import json
import logging
import os
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from queue import Empty, Queue
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
# When frozen by PyInstaller, sys.executable is the .exe; bundled data (static)
# lives in sys._MEIPASS. Engines/models/output/logs sit next to the .exe.
if getattr(sys, "frozen", False):
    APP_DIR    = Path(sys.executable).parent
    BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", APP_DIR))
else:
    APP_DIR    = Path(__file__).parent
    BUNDLE_DIR = APP_DIR

ROOT       = APP_DIR
EXE_NAME   = "sd-server.exe" if os.name == "nt" else "sd-server"
# Default output folder (user can override in Settings); kept in Pictures
# so it's easy to find and survives app updates.
DEFAULT_OUTPUT_DIR = Path.home() / "Pictures" / "AiG"
LOG_DIR    = ROOT / "logs"
STATIC_DIR = BUNDLE_DIR / "static"
CONFIG_FILE = ROOT / "config.json"
LOG_DIR.mkdir(exist_ok=True)

# Engine candidates, tried in order: fastest GPU first, then CPU fallback.
# Each engine lives in its own folder (own DLLs) to avoid conflicts.
# device pref (config "device"): "auto" | "gpu" | "cpu".
def engine_base_dirs():
    """Folders to scan for engines: the app dir, plus a user-specified one."""
    dirs = [ROOT]
    ed = load_config().get("engine_dir")
    if ed:
        p = Path(ed)
        if p not in dirs:
            dirs.append(p)
    return dirs

def engine_candidates():
    all_e = []
    seen = set()
    for base in engine_base_dirs():
        for label, sub in (("cuda", "engine-cuda"),
                           ("vulkan", "engine-vulkan"),
                           ("cpu", "engine-cpu")):
            exe = base / sub / EXE_NAME
            if exe.exists() and label not in seen:
                all_e.append((label, exe)); seen.add(label)
        flat = base / EXE_NAME       # flat fallback (single engine / macOS dev)
        if flat.exists() and "gpu" not in seen:
            all_e.append(("gpu", flat)); seen.add("gpu")

    dev = load_config().get("device", "auto")
    if dev == "cpu":
        filtered = [e for e in all_e if e[0] == "cpu"]
    elif dev == "gpu":
        filtered = [e for e in all_e if e[0] != "cpu"]
    else:
        filtered = all_e
    return filtered or all_e          # never return empty

# ---------------------------------------------------------------------------
# Config — model_dir can be set by installer or user at any time
# ---------------------------------------------------------------------------
DEFAULT_MODEL_DIR = ROOT / "models"

def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}

def save_config(cfg: dict):
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")

def get_model_dir() -> Path:
    cfg = load_config()
    p = cfg.get("model_dir")
    return Path(p) if p else DEFAULT_MODEL_DIR

def get_output_dir() -> Path:
    cfg = load_config()
    p = cfg.get("output_dir")
    d = Path(p) if p else DEFAULT_OUTPUT_DIR
    try:
        d.mkdir(parents=True, exist_ok=True)
    except Exception:
        d = DEFAULT_OUTPUT_DIR
        d.mkdir(parents=True, exist_ok=True)
    return d

def model_paths():
    d = get_model_dir()
    return {
        "dir":  d,
        "diff": d / "z_image_turbo-Q4_K.gguf",
        "vae":  d / "ae.safetensors",
        "llm":  d / "Qwen3-4B-Q4_K_M.gguf",
    }

def models_ready() -> bool:
    m = model_paths()
    return m["diff"].exists() and m["vae"].exists() and m["llm"].exists()

SD_PORT            = int(os.environ.get("SD_SERVER_PORT", "8190"))
SD_URL             = f"http://127.0.0.1:{SD_PORT}"
SD_READY_TIMEOUT   = 300
API_PORT           = int(os.environ.get("PORT", "8080"))

from collections import deque
_LOG_BUFFER: deque = deque(maxlen=400)

class _BufferHandler(logging.Handler):
    def emit(self, record):
        try:
            _LOG_BUFFER.append(self.format(record))
        except Exception:
            pass

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
_bufh = _BufferHandler()
_bufh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logging.getLogger().addHandler(_bufh)   # capture our logs in memory for the Log tab
log = logging.getLogger("zimage")

# ---------------------------------------------------------------------------
# Job store
# ---------------------------------------------------------------------------
PENDING, RUNNING, DONE, FAILED = "pending", "running", "done", "failed"
jobs: dict[str, dict] = {}
job_queue: Queue = Queue()
sd_server_proc = None
sd_status = {"state": "starting", "error": "", "engine": ""}  # starting | ready | crashed

# ---------------------------------------------------------------------------
# sd-server lifecycle
# ---------------------------------------------------------------------------
def _short_path(p: Path) -> str:
    """On Windows, return the 8.3 short path (pure ASCII) so sd-server's
    narrow-char file API can open files under non-ASCII paths (e.g. 桌面).
    Requires the file to exist; falls back to the long path otherwise."""
    sp = str(p)
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes
            _GSPN = ctypes.windll.kernel32.GetShortPathNameW
            _GSPN.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
            _GSPN.restype = wintypes.DWORD
            buf = ctypes.create_unicode_buffer(32768)
            if _GSPN(sp, buf, len(buf)):
                return buf.value
        except Exception:
            pass
    return sp


ENGINES: list = []      # populated at startup: [(label, exe), ...]
current_idx = -1        # index into ENGINES of the running engine


def _build_cmd(label, exe) -> list:
    m = model_paths()
    cmd = [
        str(exe),
        "--diffusion-model", _short_path(m["diff"]),
        "--vae",             _short_path(m["vae"]),
        "--llm",             _short_path(m["llm"]),
        "--vae-tiling",
        "--listen-port", str(SD_PORT),
        "--listen-ip",   "127.0.0.1",
    ]
    if sys.platform == "darwin":
        cmd.append("--vae-on-cpu")          # Metal VAE precision bug
    if label != "cpu":
        # Graph-cut segmented execution: auto-detect free VRAM (keep 1 GiB
        # for the desktop) and split large compute graphs to fit — lets a
        # 4 GB card render 1024+ without OOM instead of failing outright.
        cmd += ["--max-vram", "-1.0"]
        if os.name == "nt":
            cmd.append("--offload-to-cpu")  # weights stream from RAM
    if label == "cuda":
        cmd.append("--diffusion-fa")        # flash attention: smaller VRAM buffer
    # Low-VRAM mode: push text-encoder + VAE to CPU, freeing VRAM for diffusion.
    if label != "cpu" and load_config().get("low_vram"):
        cmd += ["--clip-on-cpu", "--vae-on-cpu"]
    return cmd


def _kill_port(port: int):
    """Kill whatever is listening on `port` — clears a stale sd-server left
    behind by a previous crash / force-kill so a fresh start is clean."""
    try:
        if os.name == "nt":
            out = subprocess.run(["netstat", "-ano", "-p", "tcp"],
                                 capture_output=True, text=True).stdout
            pids = {ln.split()[-1] for ln in out.splitlines()
                    if (":%d " % port) in ln and "LISTENING" in ln}
            for pid in pids:
                if pid.isdigit():
                    subprocess.run(["taskkill", "/PID", pid, "/F"], capture_output=True)
                    log.warning("Cleared stale process %s on port %d", pid, port)
        else:
            out = subprocess.run(["lsof", "-ti", "tcp:%d" % port],
                                 capture_output=True, text=True).stdout
            for pid in out.split():
                try:
                    os.kill(int(pid), 9)
                    log.warning("Cleared stale process %s on port %d", pid, port)
                except Exception:
                    pass
    except Exception as e:
        log.warning("port cleanup on %d failed: %s", port, e)


def _launch(label, exe) -> bool:
    """Start sd-server for one engine and wait until it answers HTTP.
    Returns True if the server came up, False if it exited or timed out."""
    global sd_server_proc
    _kill_port(SD_PORT)              # ensure no stale engine holds the port
    log_path = LOG_DIR / "sd_server.log"
    log.info("Starting sd-server [%s engine] on port %d …", label, SD_PORT)
    sd_status["state"]  = "starting"
    sd_status["engine"] = label
    sd_server_proc = subprocess.Popen(
        _build_cmd(label, exe),
        stdout=open(log_path, "w", encoding="utf-8"), stderr=subprocess.STDOUT,
    )
    for _ in range(SD_READY_TIMEOUT):
        time.sleep(1)
        try:
            if httpx.get(f"{SD_URL}/", timeout=2).status_code == 200:
                return True
        except Exception:
            pass
        if sd_server_proc.poll() is not None:
            return False
    try: sd_server_proc.terminate()
    except Exception: pass
    return False


def start_sd_server() -> bool:
    """Bring up the first engine that loads (GPU first, then CPU)."""
    global ENGINES, current_idx

    m = model_paths()
    missing = [str(p) for p in [m["diff"], m["vae"], m["llm"]] if not p.exists()]
    if missing:
        sd_status["state"] = "crashed"
        sd_status["error"] = "找不到模型檔案：\n" + "\n".join(missing)
        log.error("Missing files: %s", missing)
        return False

    ENGINES = engine_candidates()
    if not ENGINES:
        sd_status["state"] = "crashed"
        sd_status["error"] = "找不到 sd-server 執行檔（engine-vulkan / engine-cpu）"
        return False

    for idx, (label, exe) in enumerate(ENGINES):
        if _launch(label, exe):
            current_idx = idx
            sd_status["state"] = "ready"
            log.info("sd-server ready [%s engine]", label)
            return True
        sd_status["error"] = _log_tail(LOG_DIR / "sd_server.log")
        log.error("sd-server [%s engine] failed to start.", label)
        if idx < len(ENGINES) - 1:
            log.warning("Trying next engine…")
        time.sleep(2)

    sd_status["state"] = "crashed"
    log.error("All engines failed to start.")
    return False


def fallback_to_next_engine() -> bool:
    """Switch to the next engine after a generation failure (e.g. GPU OOM on
    a large image). Restarts sd-server on that engine. True if it came up."""
    global current_idx
    for idx in range(current_idx + 1, len(ENGINES)):
        label, exe = ENGINES[idx]
        log.warning("Generation failed — switching to [%s engine]…", label)
        try:
            if sd_server_proc: sd_server_proc.terminate()
        except Exception: pass
        time.sleep(2)
        if _launch(label, exe):
            current_idx = idx
            sd_status["state"] = "ready"
            log.info("Now running on [%s engine].", label)
            return True
    return False


def _log_tail(path: Path, lines: int = 15) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
        # collapse progress-bar carriage returns
        text = text.replace("\r", "\n")
        rows = [r for r in text.splitlines() if r.strip()]
        return "\n".join(rows[-lines:])
    except Exception:
        return ""


def sd_alive() -> bool:
    try:
        return httpx.get(f"{SD_URL}/", timeout=2).status_code == 200
    except Exception:
        return False


def _make_filename(prompt: str, job_id: str, out_dir: Path, ext: str = "png") -> str:
    """YYYYMMDD_HHMMSS_<prompt-slug>.png — sortable and recognisable.
    Keeps CJK/letters/digits; replaces filesystem-unsafe chars; falls back
    to a short id to avoid same-second collisions."""
    import re
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = re.sub(r'[\\/:*?"<>|\s]+', "-", (prompt or "").strip())[:40].strip("-")
    name = f"{ts}_{slug}" if slug else ts
    if (out_dir / f"{name}.{ext}").exists():
        name = f"{name}_{job_id[:6]}"
    return f"{name}.{ext}"


# ---------------------------------------------------------------------------
# Worker thread
# ---------------------------------------------------------------------------
def worker():
    log.info("Worker thread ready.")
    while True:
        try:
            job_id = job_queue.get(timeout=1)
        except Empty:
            continue

        job = jobs.get(job_id)
        if not job:
            continue

        job["status"]     = RUNNING
        job["started_at"] = datetime.now().isoformat()
        log.info("[%s] start: %s…", job_id[:8], job["prompt"][:60])

        out_dir = get_output_dir()
        fmt = (job.get("format") or "png").lower()
        if fmt not in ("png", "jpg"):
            fmt = "png"
        out_path = out_dir / _make_filename(job["prompt"], job_id, out_dir, fmt)
        t0 = time.monotonic()

        payload = {
            "prompt":          job["prompt"],
            "negative_prompt": job.get("negative_prompt", ""),
            "width":           job["width"],
            "height":          job["height"],
            "steps":           job["steps"],
            "cfg_scale":       job["cfg_scale"],
            "seed":            job["seed"],
            "batch_size":      1,
            "save_images":     True,
        }

        def _try_generate():
            """Returns (ok, response_or_none, error_str)."""
            try:
                resp = httpx.post(f"{SD_URL}/sdapi/v1/txt2img", json=payload, timeout=3600)
                return (resp.status_code == 200, resp, "" if resp.status_code == 200
                        else f"sd-server {resp.status_code}: {resp.text[:200]}")
            except Exception as e:
                return (False, None, str(e))

        ok, r, err = _try_generate()

        # A GPU engine likely ran out of VRAM on this resolution — fall back
        # to the next engine (cuda→vulkan→cpu) and retry the same job.
        if not ok and sd_status.get("engine") != "cpu" and current_idx < len(ENGINES) - 1:
            log.warning("[%s] generation failed on %s engine (%s) — switching…",
                        job_id[:8], sd_status.get("engine"), err[:80])
            job["status"] = "running"   # keep UI in 'generating' state
            if fallback_to_next_engine():
                t0 = time.monotonic()   # reset timer for the CPU attempt
                ok, r, err = _try_generate()

        elapsed = time.monotonic() - t0
        if ok and r is not None:
            img_b64 = r.json()["images"][0]
            raw = base64.b64decode(img_b64)
            if fmt == "jpg":
                try:
                    import io
                    from PIL import Image
                    Image.open(io.BytesIO(raw)).convert("RGB").save(str(out_path), "JPEG", quality=99, optimize=True)
                except Exception as e:
                    log.warning("JPG convert failed (%s), saving PNG", e)
                    out_path = out_path.with_suffix(".png")
                    out_path.write_bytes(raw)
            else:
                out_path.write_bytes(raw)
            job["status"]           = DONE
            job["output_file"]      = str(out_path)
            job["duration_seconds"] = round(elapsed, 1)
            job["engine"]           = sd_status.get("engine", "")
            log.info("[%s] done in %.1fs on %s", job_id[:8], elapsed, sd_status.get("engine"))
        else:
            job["status"] = FAILED
            job["error"]  = err
            log.error("[%s] failed: %s", job_id[:8], err)

        job["finished_at"] = datetime.now().isoformat()
        job_queue.task_done()


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(title="Z-Image Generator", docs_url="/api/docs")

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def _pid_alive(pid: int) -> bool:
    try:
        if os.name == "nt":
            import ctypes
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            h = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not h:
                return False
            ctypes.windll.kernel32.CloseHandle(h)
            return True
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def _watch_parent():
    """Exit (killing sd-server) if the Electron parent dies — covers the
    case where Electron is force-killed and its JS cleanup never runs."""
    ppid_env = os.environ.get("ELECTRON_PID")
    watch_pid = int(ppid_env) if ppid_env and ppid_env.isdigit() else None
    while True:
        time.sleep(3)
        orphaned = (os.name != "nt" and os.getppid() == 1)
        gone = (watch_pid is not None and not _pid_alive(watch_pid))
        if orphaned or gone:
            log.info("Parent process gone — shutting down backend.")
            _shutdown()
            os._exit(0)


# --- Engine auto-download (Windows): not bundled, fetched on first run -----
_SD_REL = "https://github.com/leejet/stable-diffusion.cpp/releases/download/master-660-d2797b8"
ENGINE_ZIPS = {
    "vulkan": [_SD_REL + "/sd-master-d2797b8-bin-win-vulkan-x64.zip"],
    "cpu":    [_SD_REL + "/sd-master-d2797b8-bin-win-avx2-x64.zip"],
    "cuda":   [_SD_REL + "/sd-master-d2797b8-bin-win-cuda12-x64.zip",
               _SD_REL + "/cudart-sd-bin-win-cu12-x64.zip"],
}
engine_dl = {"active": False, "pct": 0, "label": "", "done": False, "error": ""}

def _engines_present() -> bool:
    return len(engine_candidates()) > 0

def installed_engines() -> list:
    """Which engine groups are currently available (by label)."""
    return [label for label, _ in engine_candidates()]

def _download_engines(labels):
    import urllib.request, zipfile
    engine_dl.update(active=True, done=False, error="", pct=0, label="")
    try:
        for label in labels:
            dest = ROOT / ("engine-" + label)
            dest.mkdir(parents=True, exist_ok=True)
            for i, url in enumerate(ENGINE_ZIPS.get(label, [])):
                engine_dl["label"] = label
                def hook(c, b, t):
                    if t > 0:
                        engine_dl["pct"] = min(100, c * b * 100 // t)
                tmp = str(dest / f"_dl{i}.zip")
                urllib.request.urlretrieve(url, tmp, reporthook=hook)
                with zipfile.ZipFile(tmp) as z:
                    for m in z.namelist():
                        if m.lower().endswith((".exe", ".dll")):
                            (dest / Path(m).name).write_bytes(z.read(m))
                os.remove(tmp)
        engine_dl.update(active=False, done=True, pct=100, label="")
        log.info("Engine download complete.")
    except Exception as e:
        engine_dl.update(active=False, error=str(e))
        log.error("Engine download failed: %s", e)


def _boot():
    # No auto-download — the app opens immediately and the user chooses what
    # to fetch (or points at an existing folder) from the first-run screen.
    # If engines + models are already present, this brings sd-server up.
    start_sd_server()


@app.on_event("startup")
def startup():
    threading.Thread(target=worker, daemon=True).start()
    threading.Thread(target=_boot, daemon=True).start()
    if os.environ.get("ELECTRON_PID") or getattr(sys, "frozen", False):
        threading.Thread(target=_watch_parent, daemon=True).start()


@app.on_event("shutdown")
def shutdown():
    if sd_server_proc:
        sd_server_proc.terminate()


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------
class GenerateRequest(BaseModel):
    prompt:          str
    negative_prompt: str  = ""
    width:           int  = Field(1024, ge=256, le=2048)
    height:          int  = Field(1024, ge=256, le=2048)
    steps:           int  = Field(4, ge=1, le=50)
    cfg_scale:       float = Field(1.0, ge=0.1, le=20.0)
    seed:            int  = Field(-1)
    format:          str  = Field("jpg")


@app.post("/generate")
def generate(req: GenerateRequest):
    if not sd_alive():
        raise HTTPException(503, "sd-server not ready yet — please wait")

    job_id = str(uuid.uuid4())
    if req.seed < 0:
        import random
        req.seed = random.randint(0, 2**32 - 1)

    jobs[job_id] = {
        "job_id":     job_id,
        "status":     PENDING,
        "prompt":     req.prompt,
        "negative_prompt": req.negative_prompt,
        "width":      req.width,
        "height":     req.height,
        "steps":      req.steps,
        "cfg_scale":  req.cfg_scale,
        "seed":       req.seed,
        "format":     req.format,
        "created_at": datetime.now().isoformat(),
        "started_at": None,
        "finished_at": None,
        "output_file": None,
        "error":      None,
        "duration_seconds": None,
    }
    job_queue.put(job_id)
    return jobs[job_id]


@app.get("/jobs/{job_id}")
def get_job(job_id: str):
    if job_id not in jobs:
        raise HTTPException(404, "Job not found")
    return jobs[job_id]


@app.get("/jobs")
def list_jobs(status: Optional[str] = None):
    result = list(jobs.values())
    if status:
        result = [j for j in result if j["status"] == status]
    return sorted(result, key=lambda j: j["created_at"], reverse=True)


@app.get("/images/{job_id}")
def get_image(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job["status"] != DONE:
        raise HTTPException(400, f"Job status: {job['status']}")
    path = Path(job["output_file"])
    if not path.exists():
        raise HTTPException(404, "Image file missing")
    return FileResponse(str(path), media_type="image/png")


@app.delete("/jobs/{job_id}")
def delete_job(job_id: str):
    if job_id not in jobs:
        raise HTTPException(404, "Job not found")
    job = jobs.pop(job_id)
    if job.get("output_file"):
        p = Path(job["output_file"])
        if p.exists():
            p.unlink()
    return {"deleted": job_id}


@app.get("/health")
def health():
    m = model_paths()
    return {
        "status": "ok",
        "sd_server_ready": sd_alive(),
        "models_ready": models_ready(),
        "model_dir": str(m["dir"]),
        "engine": sd_status.get("engine", ""),
        "queue_depth": job_queue.qsize(),
        "running_jobs": sum(1 for j in jobs.values() if j["status"] == RUNNING),
        "total_jobs": len(jobs),
    }


@app.get("/loadprogress")
def loadprogress():
    """Parse sd_server.log to estimate model-loading progress (tensor count)."""
    import re
    if engine_dl["active"]:
        return {"phase": "engine", "pct": engine_dl["pct"], "label": engine_dl["label"]}
    if sd_status["state"] == "crashed":
        return {"phase": "crashed", "pct": 0, "error": sd_status["error"]}
    log_path = LOG_DIR / "sd_server.log"
    if not log_path.exists():
        return {"phase": "starting", "pct": 0}
    try:
        text = log_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return {"phase": "starting", "pct": 0}

    if "model files processing completed" in text or "loading tensors completed" in text:
        # tensors loaded; sd-server is finishing init (Metal/Vulkan warmup)
        return {"phase": "warmup", "pct": 99}

    matches = re.findall(r"(\d+)/(\d+)", text)
    if matches:
        loaded, total = int(matches[-1][0]), int(matches[-1][1])
        if total > 0:
            return {"phase": "loading", "pct": min(98, round(loaded / total * 100)),
                    "loaded": loaded, "total": total}
    return {"phase": "starting", "pct": 0}


class ConfigRequest(BaseModel):
    model_dir: Optional[str] = None
    output_dir: Optional[str] = None
    model_urls: Optional[dict] = None
    engine_dir: Optional[str] = None

@app.get("/config")
def get_config_endpoint():
    m = model_paths()
    cfg = load_config()
    urls = get_model_urls()
    files = {"z_image_turbo-Q4_K.gguf": m["diff"], "ae.safetensors": m["vae"], "Qwen3-4B-Q4_K_M.gguf": m["llm"]}
    return {
        "model_dir": str(m["dir"]),
        "output_dir": str(get_output_dir()),
        "device": cfg.get("device", "auto"),
        "low_vram": bool(cfg.get("low_vram", False)),
        "models_ready": models_ready(),
        "missing": [f for f, p in files.items() if not p.exists()],
        "engine_dir": cfg.get("engine_dir", ""),
        "engines_ready": _engines_present(),
        "engines_installed": installed_engines(),   # subset of cuda/vulkan/cpu/gpu
        "models": [{"name": f, "exists": p.exists(), "url": urls.get(f, ""),
                    "role": MODEL_META.get(f, {}).get("role", ""),
                    "license": MODEL_META.get(f, {}).get("license", ""),
                    "source": MODEL_META.get(f, {}).get("source", "")}
                   for f, p in files.items()],
    }

@app.post("/config")
def set_config_endpoint(req: ConfigRequest):
    cfg = load_config()
    if req.model_dir is not None:
        cfg["model_dir"] = str(Path(req.model_dir))
    if req.output_dir is not None:
        cfg["output_dir"] = str(Path(req.output_dir))
    if req.model_urls is not None:
        cfg["model_urls"] = {k: v for k, v in req.model_urls.items() if k in MODEL_FILES}
    if req.engine_dir is not None:
        cfg["engine_dir"] = str(Path(req.engine_dir)) if req.engine_dir else ""
    save_config(cfg)
    # Pointing at an existing engine folder may make an engine available now.
    if req.engine_dir is not None and _engines_present() and not sd_alive():
        threading.Thread(target=start_sd_server, daemon=True).start()
    ready = models_ready()
    # Models just became available → bring the engine up.
    if ready and sd_status.get("state") not in ("ready", "starting"):
        threading.Thread(target=start_sd_server, daemon=True).start()
    return {"model_dir": str(get_model_dir()), "output_dir": str(get_output_dir()), "models_ready": ready}


class EngineRequest(BaseModel):
    device: Optional[str] = None      # auto | gpu | cpu
    low_vram: Optional[bool] = None

def restart_engine():
    global sd_server_proc
    try:
        if sd_server_proc:
            sd_server_proc.terminate()
    except Exception:
        pass
    time.sleep(1)
    _kill_port(SD_PORT)
    start_sd_server()

@app.post("/set_engine")
def set_engine(req: EngineRequest):
    cfg = load_config()
    if req.device in ("auto", "gpu", "cpu"):
        cfg["device"] = req.device
    if req.low_vram is not None:
        cfg["low_vram"] = bool(req.low_vram)
    save_config(cfg)
    threading.Thread(target=restart_engine, daemon=True).start()
    return {"device": cfg.get("device", "auto"), "low_vram": bool(cfg.get("low_vram", False)), "restarting": True}


class EngineDLRequest(BaseModel):
    which: Optional[list] = None     # subset of ["vulkan","cpu","cuda"]; default = recommended

def _download_engines_then_start(labels):
    _download_engines(labels)
    if not engine_dl.get("error"):
        start_sd_server()

@app.post("/download_engine")
def download_engine(req: EngineDLRequest):
    if os.name != "nt":
        return {"active": False, "error": "引擎下載僅支援 Windows；其他平台請手動放入引擎。"}
    if engine_dl.get("active"):
        return {"active": True, "label": engine_dl.get("label", "")}
    labels = [l for l in (req.which or ["vulkan", "cpu"]) if l in ENGINE_ZIPS]
    if not labels:
        labels = ["vulkan", "cpu"]
    threading.Thread(target=_download_engines_then_start, args=(labels,), daemon=True).start()
    return {"active": True, "which": labels}

@app.get("/engine_status")
def engine_status():
    return {**engine_dl, "installed": installed_engines()}


@app.get("/logs")
def get_logs():
    return {
        "app":       "\n".join(_LOG_BUFFER),
        "sd_server": _log_tail(LOG_DIR / "sd_server.log", lines=150),
        "engine":    sd_status.get("engine", ""),
        "state":     sd_status.get("state", ""),
    }


# --- Model download (replaces download_models.bat) -------------------------
download_state = {"active": False, "pct": 0, "file": "", "done": False, "error": ""}

MODEL_FILES = ["z_image_turbo-Q4_K.gguf", "ae.safetensors", "Qwen3-4B-Q4_K_M.gguf"]
# Ungated, no-login direct-download mirrors (verified):
DEFAULT_URLS = {
    "z_image_turbo-Q4_K.gguf": "https://huggingface.co/leejet/Z-Image-Turbo-GGUF/resolve/main/z_image_turbo-Q4_K.gguf",
    "ae.safetensors":          "https://huggingface.co/Comfy-Org/z_image_turbo/resolve/main/split_files/vae/ae.safetensors",
    "Qwen3-4B-Q4_K_M.gguf":    "https://huggingface.co/unsloth/Qwen3-4B-Instruct-2507-GGUF/resolve/main/Qwen3-4B-Instruct-2507-Q4_K_M.gguf",
}

MODEL_META = {
    "z_image_turbo-Q4_K.gguf": {"role": "擴散模型（畫師）", "license": "Apache 2.0", "source": "Tongyi-MAI/Z-Image-Turbo"},
    "ae.safetensors":          {"role": "VAE（解碼成圖）",  "license": "Apache 2.0", "source": "black-forest-labs/FLUX.1-schnell"},
    "Qwen3-4B-Q4_K_M.gguf":    {"role": "文字編碼（翻譯）", "license": "Apache 2.0", "source": "Qwen/Qwen3-4B"},
}

def get_model_urls() -> dict:
    """Per-file download URLs; config overrides take precedence."""
    urls = dict(DEFAULT_URLS)
    urls.update(load_config().get("model_urls", {}) or {})
    return urls


def _download_thread(dest: Path, only: Optional[str] = None):
    import urllib.request
    urls = get_model_urls()
    download_state.update(active=True, done=False, error="", pct=0, file="")
    try:
        dest.mkdir(parents=True, exist_ok=True)
        targets = [only] if only else MODEL_FILES
        for fname in targets:
            url = urls.get(fname)
            out = dest / fname
            # skip existing only in "download all missing" mode; a single-file
            # request always (re)downloads so a user can swap models.
            if not only and out.exists() and out.stat().st_size > 0:
                continue
            if not url:
                continue
            download_state["file"] = fname
            download_state["pct"]  = 0

            def hook(count, block, total):
                if total > 0:
                    download_state["pct"] = min(100, count * block * 100 // total)

            tmp = str(out) + ".part"
            urllib.request.urlretrieve(url, tmp, reporthook=hook)
            os.replace(tmp, str(out))
        download_state.update(active=False, done=True, pct=100, file="")
        log.info("Model download complete.")
        if models_ready() and sd_status.get("state") != "ready":
            threading.Thread(target=start_sd_server, daemon=True).start()
    except Exception as e:
        download_state.update(active=False, error=str(e))
        log.error("Model download failed: %s", e)


class DownloadRequest(BaseModel):
    file: Optional[str] = None

@app.post("/download_models")
def download_models(req: DownloadRequest = DownloadRequest()):
    if download_state["active"]:
        return {"active": True}
    only = req.file if (req and req.file in MODEL_FILES) else None
    threading.Thread(target=_download_thread, args=(get_model_dir(), only), daemon=True).start()
    return {"active": True, "file": only}


@app.get("/download_status")
def download_status():
    return download_state


@app.get("/translate")
def translate(q: str, tl: str = "zh-TW", sl: str = "auto"):
    """Display-only translation via Google's free endpoint (needs internet).
    Used to show the Chinese meaning of an English prompt — does not change
    what is sent to the model."""
    try:
        r = httpx.get("https://translate.googleapis.com/translate_a/single",
                      params={"client": "gtx", "sl": sl, "tl": tl, "dt": "t", "q": q},
                      timeout=10)
        data = r.json()
        text = "".join(seg[0] for seg in data[0] if seg and seg[0])
        return {"text": text}
    except Exception as e:
        return {"text": "", "error": str(e)}


@app.get("/output_dir")
def output_dir():
    return {"path": str(get_output_dir())}


@app.post("/open_output")
def open_output():
    try:
        d = get_output_dir()
        if sys.platform == "darwin":
            subprocess.run(["open", str(d)])
        elif os.name == "nt":
            os.startfile(str(d))   # type: ignore[attr-defined]
        else:
            subprocess.run(["xdg-open", str(d)])
        return {"ok": True, "path": str(d)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/")
def index():
    idx = STATIC_DIR / "index.html"
    if idx.exists():
        return FileResponse(str(idx), headers={"Cache-Control": "no-store, max-age=0"})
    return HTMLResponse("<h1>Amazing image Generator</h1><p>static/index.html not found</p>")


# ---------------------------------------------------------------------------
def _serve():
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=API_PORT, log_level="warning")


def _wait_health(timeout_s: int = 40) -> bool:
    for _ in range(timeout_s * 2):
        try:
            if httpx.get(f"http://127.0.0.1:{API_PORT}/health", timeout=1).status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def _shutdown():
    try:
        if sd_server_proc:
            sd_server_proc.terminate()
    except Exception:
        pass


def _install_signal_shutdown():
    """Terminate sd-server when this process is asked to stop (Electron sends
    SIGTERM / taskkill on app close)."""
    import signal
    def _handler(signum, frame):
        log.info("Received signal %s — shutting down.", signum)
        _shutdown()
        os._exit(0)
    for s in (signal.SIGTERM, signal.SIGINT):
        try: signal.signal(s, _handler)
        except Exception: pass


if __name__ == "__main__":
    # Headless backend. The Electron shell owns the window and lifecycle;
    # it spawns this process and kills it (tree-kill) when the app closes.
    _install_signal_shutdown()
    import atexit
    atexit.register(_shutdown)
    _serve()
