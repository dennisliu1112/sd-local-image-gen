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
# Paths — resolved relative to this script so it works from any directory
# ---------------------------------------------------------------------------
ROOT       = Path(__file__).parent
EXE        = ROOT / ("sd-server.exe" if os.name == "nt" else "sd-server")
MODEL_DIR  = ROOT / "models"
DIFF_MODEL = MODEL_DIR / "z_image_turbo-Q4_K.gguf"
VAE_MODEL  = MODEL_DIR / "ae.safetensors"
LLM_MODEL  = MODEL_DIR / "Qwen3-4B-Q4_K_M.gguf"
OUTPUT_DIR = ROOT / "output"
LOG_DIR    = ROOT / "logs"
STATIC_DIR = ROOT / "static"

OUTPUT_DIR.mkdir(exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)

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

# ---------------------------------------------------------------------------
# sd-server lifecycle
# ---------------------------------------------------------------------------
def start_sd_server() -> bool:
    global sd_server_proc

    missing = [str(p) for p in [EXE, DIFF_MODEL, VAE_MODEL, LLM_MODEL] if not p.exists()]
    if missing:
        log.error("Missing files: %s", missing)
        return False

    cmd = [
        str(EXE),
        "--diffusion-model", str(DIFF_MODEL),
        "--vae",             str(VAE_MODEL),
        "--llm",             str(LLM_MODEL),
        "--vae-tiling",
        "--listen-port", str(SD_PORT),
        "--listen-ip",   "127.0.0.1",
    ]

    # On macOS Metal the VAE has a precision bug — run it on CPU
    if sys.platform == "darwin":
        cmd.append("--vae-on-cpu")

    log_path = LOG_DIR / "sd_server.log"
    log.info("Starting sd-server on port %d …", SD_PORT)
    sd_server_proc = subprocess.Popen(
        cmd,
        stdout=open(log_path, "w", encoding="utf-8"),
        stderr=subprocess.STDOUT,
    )

    for i in range(SD_READY_TIMEOUT):
        time.sleep(1)
        try:
            r = httpx.get(f"{SD_URL}/", timeout=2)
            if r.status_code == 200:
                log.info("sd-server ready after %ds", i + 1)
                return True
        except Exception:
            pass
        if sd_server_proc.poll() is not None:
            log.error("sd-server exited unexpectedly")
            return False

    log.error("sd-server did not start within %ds", SD_READY_TIMEOUT)
    return False


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
        job["started_at"] = datetime.utcnow().isoformat()
        log.info("[%s] start: %s…", job_id[:8], job["prompt"][:60])

        out_path = OUTPUT_DIR / f"{job_id}.png"
        t0 = time.monotonic()

        try:
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
            r = httpx.post(f"{SD_URL}/sdapi/v1/txt2img", json=payload, timeout=3600)
            elapsed = time.monotonic() - t0

            if r.status_code == 200:
                img_b64 = r.json()["images"][0]
                out_path.write_bytes(base64.b64decode(img_b64))
                job["status"]           = DONE
                job["output_file"]      = str(out_path)
                job["duration_seconds"] = round(elapsed, 1)
                log.info("[%s] done in %.1fs", job_id[:8], elapsed)
            else:
                job["status"] = FAILED
                job["error"]  = f"sd-server {r.status_code}: {r.text[:200]}"
        except Exception as exc:
            job["status"] = FAILED
            job["error"]  = str(exc)
            log.error("[%s] error: %s", job_id[:8], exc)

        job["finished_at"] = datetime.utcnow().isoformat()
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
        "created_at": datetime.utcnow().isoformat(),
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
    return {
        "status": "ok",
        "sd_server_ready": sd_alive(),
        "queue_depth": job_queue.qsize(),
        "running_jobs": sum(1 for j in jobs.values() if j["status"] == RUNNING),
        "total_jobs": len(jobs),
    }


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
