"""
Stable Diffusion API Server
Manages sd-server.exe and exposes a REST job queue with character presets.

Endpoints:
  POST /generate             - Submit job (character+scene or raw prompt)
  GET  /jobs/{job_id}        - Job status
  GET  /jobs                 - List jobs (?status= ?character=)
  GET  /images/{job_id}      - Download image
  DELETE /jobs/{job_id}      - Remove job
  GET  /characters           - List character presets
  GET  /characters/{id}      - Character detail
  POST /characters/{id}/preview - Preview assembled prompt
  GET  /health               - Health check

Run:
  python sd_api.py
"""

import importlib.util
import json
import logging
import os
import subprocess
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from queue import Queue, Empty
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT        = Path(__file__).parent
EXE         = ROOT / "src" / "build" / "bin" / ("sd-server.exe" if os.name == "nt" else "sd-server")
DIFF_MODEL  = ROOT / "models" / "z_image_turbo-Q4_K.gguf"
VAE_MODEL   = ROOT / "models" / "ae.safetensors"
LLM_MODEL   = ROOT / "models" / "Qwen3-4B-Q4_K_M.gguf"
OUTPUT_DIR  = ROOT / "eval"
LOG_DIR     = ROOT / "logs"

OUTPUT_DIR.mkdir(exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)

SD_SERVER_PORT = int(os.environ.get("SD_SERVER_PORT", "8190"))
SD_SERVER_URL  = f"http://127.0.0.1:{SD_SERVER_PORT}"
SD_SERVER_READY_TIMEOUT = 300  # seconds to wait for sd-server to boot

# ---------------------------------------------------------------------------
# Character definitions
# ---------------------------------------------------------------------------
def _load_char_mod():
    p = ROOT / "sd_characters.py"
    if not p.exists():
        return None
    spec = importlib.util.spec_from_file_location("sd_characters", p)
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

_cm = _load_char_mod()
CHARACTERS      = _cm.CHARACTERS      if _cm else {}
build_prompt    = _cm.build_prompt    if _cm else None
list_characters = _cm.list_characters if _cm else lambda: []

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "sd_api.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("sd_api")

# ---------------------------------------------------------------------------
# Job store
# ---------------------------------------------------------------------------
PENDING = "pending"
RUNNING = "running"
DONE    = "done"
FAILED  = "failed"

jobs: dict[str, dict] = {}
job_queue: Queue = Queue()
sd_server_proc: Optional[subprocess.Popen] = None

# ---------------------------------------------------------------------------
# sd-server management
# ---------------------------------------------------------------------------
def start_sd_server():
    global sd_server_proc
    if not EXE.exists():
        log.error(f"sd-server not found: {EXE}")
        return False

    cmd = [
        str(EXE),
        "--diffusion-model", str(DIFF_MODEL),
        "--vae",             str(VAE_MODEL),
        "--llm",             str(LLM_MODEL),
        "--vae-tiling", "--offload-to-cpu",
        "--listen-port", str(SD_SERVER_PORT),
        "--listen-ip", "127.0.0.1",
    ]

    log_path = LOG_DIR / "sd_server.log"
    log.info(f"Starting sd-server on port {SD_SERVER_PORT}...")
    sd_server_proc = subprocess.Popen(
        cmd,
        stdout=open(log_path, "w", encoding="utf-8"),
        stderr=subprocess.STDOUT,
    )

    # Wait until ready
    for i in range(SD_SERVER_READY_TIMEOUT):
        time.sleep(1)
        try:
            r = httpx.get(f"{SD_SERVER_URL}/", timeout=2)
            if r.status_code == 200:
                log.info(f"sd-server ready after {i+1}s")
                return True
        except Exception:
            pass
        if sd_server_proc.poll() is not None:
            log.error("sd-server exited unexpectedly")
            return False

    log.error("sd-server did not become ready in time")
    return False


def sd_server_alive() -> bool:
    try:
        r = httpx.get(f"{SD_SERVER_URL}/", timeout=2)
        return r.status_code == 200
    except Exception:
        return False

# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------
def worker():
    log.info("Worker thread started.")
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
        log.info(f"[{job_id}] Start: {job['prompt'][:60]}...")

        output_path = OUTPUT_DIR / f"{job_id}.png"
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

            r = httpx.post(
                f"{SD_SERVER_URL}/sdapi/v1/txt2img",
                json=payload,
                timeout=3600,  # 1 hour — generation can be slow
            )
            elapsed = time.monotonic() - t0

            if r.status_code == 200:
                data = r.json()
                # sd-server returns base64 images; save to disk
                import base64
                img_b64 = data["images"][0]
                output_path.write_bytes(base64.b64decode(img_b64))
                job["status"]           = DONE
                job["output_file"]      = str(output_path)
                job["duration_seconds"] = round(elapsed, 2)
                log.info(f"[{job_id}] Done {elapsed:.1f}s → {output_path.name}")
            else:
                job["status"] = FAILED
                job["error"]  = f"sd-server returned {r.status_code}: {r.text[:200]}"
                log.error(f"[{job_id}] Failed: {r.status_code}")

        except httpx.TimeoutException:
            job["status"] = FAILED
            job["error"]  = "sd-server request timed out (1h)"
        except Exception as exc:
            job["status"] = FAILED
            job["error"]  = str(exc)
            log.error(f"[{job_id}] Exception: {exc}")

        job["finished_at"] = datetime.utcnow().isoformat()
        job_queue.task_done()

# ---------------------------------------------------------------------------
# FastAPI
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Stable Diffusion API",
    description="Local SD image generation — REST API + character presets + async job queue",
    version="3.0.0",
)

@app.on_event("startup")
def startup():
    threading.Thread(target=start_sd_server, daemon=True, name="sd-server-launcher").start()
    threading.Thread(target=worker,           daemon=True, name="sd-worker").start()
    log.info(f"API ready. Characters: {list(CHARACTERS.keys())}")

@app.on_event("shutdown")
def shutdown():
    if sd_server_proc and sd_server_proc.poll() is None:
        sd_server_proc.terminate()
        log.info("sd-server terminated.")

# ── Models ───────────────────────────────────────────────────────────────────
class GenerateRequest(BaseModel):
    prompt:          str   = Field("",    description="Custom prompt (required if no character)")
    negative_prompt: str   = Field("",   description="Negative prompt")
    character:       str   = Field("",   description="Character preset ID")
    scene:           str   = Field("S1", description="Scene ID (S1/S2/S3)")
    width:           int   = Field(1024, ge=64, le=2048)
    height:          int   = Field(1024, ge=64, le=2048)
    steps:           int   = Field(4,    ge=1,  le=50)
    cfg_scale:       float = Field(1.0,  ge=0.1, le=20.0)
    seed:            int   = Field(-1)

class JobStatus(BaseModel):
    job_id:           str
    status:           str
    character:        Optional[str]   = None
    scene:            Optional[str]   = None
    prompt:           str
    created_at:       str
    started_at:       Optional[str]   = None
    finished_at:      Optional[str]   = None
    output_file:      Optional[str]   = None
    error:            Optional[str]   = None
    duration_seconds: Optional[float] = None

# ── Generate ─────────────────────────────────────────────────────────────────
@app.post("/generate", response_model=JobStatus, status_code=202)
def generate(req: GenerateRequest):
    if not sd_server_alive():
        raise HTTPException(503, detail="sd-server not ready yet, please wait")

    if req.character:
        if req.character not in CHARACTERS:
            raise HTTPException(400, detail=f"Unknown character '{req.character}'. Available: {list(CHARACTERS.keys())}")
        prompt = build_prompt(req.character, req.scene, req.prompt)
    elif req.prompt:
        prompt = req.prompt
    else:
        raise HTTPException(400, detail="Provide 'prompt' or 'character'")

    job_id = str(uuid.uuid4())
    job = {
        "job_id":           job_id,
        "status":           PENDING,
        "character":        req.character or None,
        "scene":            req.scene if req.character else None,
        "prompt":           prompt,
        "negative_prompt":  req.negative_prompt,
        "width":            req.width,
        "height":           req.height,
        "steps":            req.steps,
        "cfg_scale":        req.cfg_scale,
        "seed":             req.seed,
        "created_at":       datetime.utcnow().isoformat(),
        "started_at":       None,
        "finished_at":      None,
        "output_file":      None,
        "error":            None,
        "duration_seconds": None,
    }
    jobs[job_id] = job
    job_queue.put(job_id)
    log.info(f"[{job_id}] Queued (char={req.character or 'custom'}, q={job_queue.qsize()})")
    return job

# ── Jobs ─────────────────────────────────────────────────────────────────────
@app.get("/jobs/{job_id}", response_model=JobStatus)
def get_job(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, detail="Job not found")
    return job

@app.get("/jobs", response_model=list[JobStatus])
def list_jobs(status: Optional[str] = None, character: Optional[str] = None):
    result = list(jobs.values())
    if status:
        result = [j for j in result if j["status"] == status]
    if character:
        result = [j for j in result if j.get("character") == character]
    return sorted(result, key=lambda j: j["created_at"], reverse=True)

@app.get("/images/{job_id}")
def get_image(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, detail="Job not found")
    if job["status"] != DONE:
        raise HTTPException(400, detail=f"Job not done (status: {job['status']})")
    path = Path(job["output_file"])
    if not path.exists():
        raise HTTPException(404, detail="Image file missing")
    return FileResponse(path, media_type="image/png", filename=f"{job_id}.png")

@app.delete("/jobs/{job_id}")
def delete_job(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, detail="Job not found")
    if job["status"] in (PENDING, RUNNING):
        raise HTTPException(400, detail="Cannot delete active job")
    if job.get("output_file"):
        Path(job["output_file"]).unlink(missing_ok=True)
    del jobs[job_id]
    return {"deleted": job_id}

# ── Characters ───────────────────────────────────────────────────────────────
@app.get("/characters")
def get_characters():
    return list_characters()

@app.get("/characters/{character_id}")
def get_character(character_id: str):
    char = CHARACTERS.get(character_id)
    if not char:
        raise HTTPException(404, detail=f"Character '{character_id}' not found")
    return {
        "id":          character_id,
        "name":        char["name"],
        "emoji":       char["emoji"],
        "description": char["description"],
        "scenes": {
            sid: {"name": s["name"], "prompt_preview": s["prompt"][:80] + "..."}
            for sid, s in char["scenes"].items()
        },
    }

@app.post("/characters/{character_id}/preview")
def preview_prompt(character_id: str, scene: str = "S1", extra: str = ""):
    if character_id not in CHARACTERS:
        raise HTTPException(404, detail=f"Character '{character_id}' not found")
    return {"prompt": build_prompt(character_id, scene, extra)}

# ── Health ────────────────────────────────────────────────────────────────────
@app.get("/health")
def health():
    return {
        "status":          "ok",
        "sd_server_ready": sd_server_alive(),
        "sd_server_url":   SD_SERVER_URL,
        "characters":      list(CHARACTERS.keys()),
        "queue_depth":     sum(1 for j in jobs.values() if j["status"] == PENDING),
        "running_jobs":    sum(1 for j in jobs.values() if j["status"] == RUNNING),
        "total_jobs":      len(jobs),
    }

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    api_port = int(os.environ.get("SD_API_PORT", "8080"))
    uvicorn.run("sd_api:app", host="0.0.0.0", port=api_port, reload=False)
