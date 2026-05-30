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
ROOT       = Path(__file__).parent
EXE_NAME   = "sd-server.exe" if os.name == "nt" else "sd-server"
OUTPUT_DIR = ROOT / "output"
LOG_DIR    = ROOT / "logs"
STATIC_DIR = ROOT / "static"
CONFIG_FILE = ROOT / "config.json"

OUTPUT_DIR.mkdir(exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)

# Engine candidates, tried in order: GPU first, then CPU fallback.
# Each engine lives in its own folder (own DLLs) to avoid conflicts.
def engine_candidates():
    out = []
    for label, sub in (("gpu", "engine-vulkan"), ("cpu", "engine-cpu")):
        exe = ROOT / sub / EXE_NAME
        if exe.exists():
            out.append((label, exe))
    # flat layout fallback (single engine / dev on macOS)
    flat = ROOT / EXE_NAME
    if flat.exists():
        out.append(("gpu", flat))
    return out

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

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

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
    if label == "gpu" and os.name == "nt":
        cmd.append("--offload-to-cpu")      # keep weights in RAM (low VRAM)
    return cmd


def _launch(label, exe) -> bool:
    """Start sd-server for one engine and wait until it answers HTTP.
    Returns True if the server came up, False if it exited or timed out."""
    global sd_server_proc
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

        out_path = OUTPUT_DIR / f"{job_id}.png"
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

        # GPU likely ran out of VRAM on this resolution — fall back to CPU and retry.
        if not ok and sd_status.get("engine") == "gpu" and current_idx < len(ENGINES) - 1:
            log.warning("[%s] generation failed on GPU (%s) — switching to CPU…",
                        job_id[:8], err[:80])
            job["status"] = "running"   # keep UI in 'generating' state
            if fallback_to_next_engine():
                t0 = time.monotonic()   # reset timer for the CPU attempt
                ok, r, err = _try_generate()

        elapsed = time.monotonic() - t0
        if ok and r is not None:
            img_b64 = r.json()["images"][0]
            out_path.write_bytes(base64.b64decode(img_b64))
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


@app.on_event("startup")
def startup():
    threading.Thread(target=worker, daemon=True).start()
    threading.Thread(target=start_sd_server, daemon=True).start()


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
    model_dir: str

@app.get("/config")
def get_config_endpoint():
    cfg = load_config()
    m = model_paths()
    return {
        "model_dir": str(m["dir"]),
        "models_ready": models_ready(),
        "missing": [
            f for f, p in [("z_image_turbo-Q4_K.gguf", m["diff"]),
                           ("ae.safetensors", m["vae"]),
                           ("Qwen3-4B-Q4_K_M.gguf", m["llm"])]
            if not p.exists()
        ],
    }

@app.post("/config")
def set_config_endpoint(req: ConfigRequest):
    p = Path(req.model_dir)
    cfg = load_config()
    cfg["model_dir"] = str(p)
    save_config(cfg)
    return {"model_dir": str(p), "models_ready": models_ready()}


@app.get("/")
def index():
    idx = STATIC_DIR / "index.html"
    if idx.exists():
        return FileResponse(str(idx))
    return HTMLResponse("<h1>Z-Image Generator</h1><p>static/index.html not found</p>")


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=API_PORT, log_level="info")
