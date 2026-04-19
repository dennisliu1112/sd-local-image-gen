#!/usr/bin/env python3
"""
sd-local-image-gen — OpenClaw skill script
HTTP client that calls the local SD API server (sd_api.py).

Required env var:
  SD_API_URL  Base URL of the SD API server (default: http://localhost:8080)

Usage:
  python gen.py --character xiaoai --scene S1
  python gen.py --prompt "1girl, beach, golden hour"
  python gen.py --status <job_id>
  python gen.py --collect <job_id> --out-dir ./output
  python gen.py --list-characters
"""

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
import urllib.error
from pathlib import Path

API_URL       = os.environ.get("SD_API_URL", "http://localhost:8080").rstrip("/")
POLL_INTERVAL = 5   # seconds between status polls
TIMEOUT       = 7200  # 2 hours max wait

# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------
def _get(path: str) -> dict:
    with urllib.request.urlopen(f"{API_URL}{path}", timeout=15) as r:
        return json.loads(r.read())

def _post(path: str, body: dict = {}) -> dict:
    data = json.dumps(body).encode()
    req  = urllib.request.Request(
        f"{API_URL}{path}", data=data,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())

def _download(path: str, dest: Path):
    urllib.request.urlretrieve(f"{API_URL}{path}", dest)

def _check_server():
    try:
        h = _get("/health")
        if not h.get("sd_server_ready"):
            print(f"WARNING: sd-server not ready yet — jobs will queue until it starts.")
        return True
    except urllib.error.URLError:
        print(f"ERROR: Cannot connect to SD API at {API_URL}")
        print(f"  Start the server: python sd_api.py  (or start_api.bat)")
        sys.exit(1)

# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------
def cmd_list_characters():
    _check_server()
    chars = _get("/characters")
    print(f"\nAvailable characters ({len(chars)}):\n")
    for c in chars:
        print(f"  {c['emoji']} {c['id']:12s}  {c['name']}  —  {c['description']}")
        for sid, sname in c["scenes"].items():
            print(f"               {sid}: {sname}")
    print()


def cmd_submit(args) -> str:
    """Submit a job, return job_id."""
    _check_server()
    body = {
        "character":       args.character,
        "scene":           args.scene,
        "prompt":          args.prompt,
        "negative_prompt": args.negative_prompt,
        "width":           args.width,
        "height":          args.height,
        "steps":           args.steps,
        "cfg_scale":       args.cfg_scale,
        "seed":            args.seed,
    }
    job = _post("/generate", body)
    job_id = job["job_id"]
    char   = job.get("character") or "custom"
    print(f"Job submitted: {job_id}")
    print(f"  Character : {char} / Scene: {job.get('scene') or '—'}")
    print(f"  Status    : {job['status']}")
    print(f"  Check     : python gen.py --status {job_id}")
    return job_id


def cmd_status(job_id: str):
    """Print job status."""
    _check_server()
    job = _get(f"/jobs/{job_id}")
    status = job["status"]
    print(f"\nJob: {job_id}")
    print(f"  Status    : {status}")
    if job.get("character"):
        print(f"  Character : {job['character']} / {job.get('scene')}")
    print(f"  Created   : {job['created_at']}")
    if job.get("started_at"):
        print(f"  Started   : {job['started_at']}")
    if job.get("finished_at"):
        print(f"  Finished  : {job['finished_at']}")
    if job.get("duration_seconds"):
        print(f"  Duration  : {job['duration_seconds']}s")
    if status == "done":
        print(f"  Image URL : {API_URL}/images/{job_id}")
        print(f"  Collect   : python gen.py --collect {job_id}")
    if status == "failed":
        print(f"  Error     : {job.get('error')}")
    print()
    return status


def cmd_collect(job_id: str, out_dir: Path):
    """Download the completed image."""
    _check_server()
    job = _get(f"/jobs/{job_id}")
    if job["status"] != "done":
        print(f"ERROR: Job not done yet (status: {job['status']})")
        sys.exit(1)

    out_dir.mkdir(parents=True, exist_ok=True)
    char = job.get("character") or "custom"
    scene = job.get("scene") or ""
    filename = f"{char}_{scene}_{job_id[:8]}.png".strip("_")
    dest = out_dir / filename

    print(f"Downloading image → {dest}")
    _download(f"/images/{job_id}", dest)
    print(f"Saved: {dest}")
    return dest


def cmd_wait_and_collect(job_id: str, out_dir: Path):
    """Poll until done, then download. For synchronous usage."""
    elapsed = 0
    while elapsed < TIMEOUT:
        job = _get(f"/jobs/{job_id}")
        status = job["status"]
        if status == "done":
            print()
            return cmd_collect(job_id, out_dir)
        if status == "failed":
            print(f"\nERROR: Job failed — {job.get('error')}")
            sys.exit(1)
        mins = elapsed // 60
        print(f"  [{mins:3d}m] {status}...", end="\r", flush=True)
        time.sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL
    print(f"\nERROR: Timed out after {TIMEOUT//60} minutes")
    sys.exit(1)

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="OpenClaw SD skill — image generation via API")

    # Actions
    parser.add_argument("--list-characters", action="store_true", help="List available character presets")
    parser.add_argument("--status",  metavar="JOB_ID", help="Check job status")
    parser.add_argument("--collect", metavar="JOB_ID", help="Download completed image")
    parser.add_argument("--wait",    metavar="JOB_ID", help="Poll until done then download (blocking)")

    # Generation
    parser.add_argument("--character",       default="",   help="Character preset ID")
    parser.add_argument("--scene",           default="S1", help="Scene ID (S1/S2/S3)")
    parser.add_argument("--prompt",          default="",   help="Custom text prompt")
    parser.add_argument("--negative-prompt", default="",   help="Negative prompt")
    parser.add_argument("--width",     type=int,   default=1024)
    parser.add_argument("--height",    type=int,   default=1024)
    parser.add_argument("--steps",     type=int,   default=4)
    parser.add_argument("--cfg-scale", type=float, default=1.0)
    parser.add_argument("--seed",      type=int,   default=-1)
    parser.add_argument("--out-dir",   default="", help="Output directory for downloaded images")

    args = parser.parse_args()
    out_dir = Path(args.out_dir) if args.out_dir else Path.home() / "Pictures" / "sd-local"

    if args.list_characters:
        cmd_list_characters()

    elif args.status:
        cmd_status(args.status)

    elif args.collect:
        cmd_collect(args.collect, out_dir)

    elif args.wait:
        cmd_wait_and_collect(args.wait, out_dir)

    elif args.character or args.prompt:
        cmd_submit(args)

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
