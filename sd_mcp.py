"""
sd_mcp.py — MCP Server for Stable Diffusion
Exposes SD generation tools to any MCP client (Claude, OpenClaw, etc.)

Agent calls us → we call sd_api.py → sd-server.exe does the work

Run:
  python sd_mcp.py

MCP clients connect via stdio (default) or SSE.
Configure in Claude / OpenClaw MCP settings:
  {
    "sd-image-gen": {
      "command": "python",
      "args": ["/path/to/SD_Windows/sd_mcp.py"]
    }
  }
  Replace /path/to/SD_Windows with the actual folder path on your computer.
  See README.md → MCP Server section for full setup instructions.
"""

import json
import os
import sys
import urllib.parse
import urllib.request
import urllib.error
from pathlib import Path

# MCP SDK
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

API_URL = os.environ.get("SD_API_URL", "http://localhost:8080").rstrip("/")

# ---------------------------------------------------------------------------
# HTTP helpers (no extra deps)
# ---------------------------------------------------------------------------
def _get(path: str) -> dict:
    req = urllib.request.Request(f"{API_URL}{path}")
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())

def _post(path: str, body: dict) -> dict:
    data = json.dumps(body).encode()
    req  = urllib.request.Request(
        f"{API_URL}{path}", data=data,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())

def _api_available() -> bool:
    try:
        _get("/health")
        return True
    except Exception:
        return False

# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------
server = Server("sd-image-gen")


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="generate_image",
            description=(
                "Submit an image generation job to the local Stable Diffusion server. "
                "Returns a job_id immediately — generation runs in background. "
                "Use get_job_status to check progress, get_image_url when done."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "character": {
                        "type": "string",
                        "description": "Character preset ID (use list_characters to see options). Leave empty for custom prompt.",
                    },
                    "scene": {
                        "type": "string",
                        "description": "Scene ID within the character preset (S1/S2/S3). Default: S1.",
                        "default": "S1",
                    },
                    "prompt": {
                        "type": "string",
                        "description": "Custom text prompt. Used directly if no character, or appended to character preset.",
                        "default": "",
                    },
                    "negative_prompt": {
                        "type": "string",
                        "description": "Negative prompt (what to avoid).",
                        "default": "",
                    },
                    "width":     {"type": "integer", "default": 1024},
                    "height":    {"type": "integer", "default": 1024},
                    "steps":     {"type": "integer", "default": 4},
                    "cfg_scale": {"type": "number",  "default": 1.0},
                    "seed":      {"type": "integer", "default": -1, "description": "-1 for random"},
                },
            },
        ),
        types.Tool(
            name="get_job_status",
            description="Check the status of an image generation job. Status: pending → running → done / failed.",
            inputSchema={
                "type": "object",
                "properties": {
                    "job_id": {"type": "string", "description": "Job ID returned by generate_image"},
                },
                "required": ["job_id"],
            },
        ),
        types.Tool(
            name="get_image_url",
            description="Get the download URL for a completed image. Only works when job status is 'done'.",
            inputSchema={
                "type": "object",
                "properties": {
                    "job_id": {"type": "string", "description": "Job ID of a completed job"},
                },
                "required": ["job_id"],
            },
        ),
        types.Tool(
            name="list_characters",
            description="List all available character presets and their scenes.",
            inputSchema={"type": "object", "properties": {}},
        ),
        types.Tool(
            name="preview_prompt",
            description="Preview the full assembled prompt for a character+scene without generating an image.",
            inputSchema={
                "type": "object",
                "properties": {
                    "character": {"type": "string", "description": "Character preset ID"},
                    "scene":     {"type": "string", "description": "Scene ID", "default": "S1"},
                    "extra":     {"type": "string", "description": "Extra tags to append", "default": ""},
                },
                "required": ["character"],
            },
        ),
        types.Tool(
            name="list_jobs",
            description="List recent generation jobs, optionally filtered by status or character.",
            inputSchema={
                "type": "object",
                "properties": {
                    "status":    {"type": "string", "description": "Filter: pending / running / done / failed"},
                    "character": {"type": "string", "description": "Filter by character ID"},
                },
            },
        ),
        types.Tool(
            name="health_check",
            description="Check if the SD API server and sd-server inference engine are running.",
            inputSchema={"type": "object", "properties": {}},
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:

    def ok(data) -> list[types.TextContent]:
        text = json.dumps(data, ensure_ascii=False, indent=2) if isinstance(data, (dict, list)) else str(data)
        return [types.TextContent(type="text", text=text)]

    def err(msg: str) -> list[types.TextContent]:
        return [types.TextContent(type="text", text=f"ERROR: {msg}")]

    if not _api_available():
        return err(f"SD API not reachable at {API_URL}. Start the server: python sd_api.py")

    try:
        if name == "generate_image":
            job = _post("/generate", {
                "character":       arguments.get("character", ""),
                "scene":           arguments.get("scene", "S1"),
                "prompt":          arguments.get("prompt", ""),
                "negative_prompt": arguments.get("negative_prompt", ""),
                "width":           arguments.get("width", 1024),
                "height":          arguments.get("height", 1024),
                "steps":           arguments.get("steps", 4),
                "cfg_scale":       arguments.get("cfg_scale", 1.0),
                "seed":            arguments.get("seed", -1),
            })
            return ok({
                "job_id":    job["job_id"],
                "status":    job["status"],
                "character": job.get("character"),
                "scene":     job.get("scene"),
                "message":   "Job submitted. Use get_job_status to check progress.",
            })

        elif name == "get_job_status":
            job = _get(f"/jobs/{arguments['job_id']}")
            result = {
                "job_id":           job["job_id"],
                "status":           job["status"],
                "character":        job.get("character"),
                "scene":            job.get("scene"),
                "created_at":       job["created_at"],
                "started_at":       job.get("started_at"),
                "finished_at":      job.get("finished_at"),
                "duration_seconds": job.get("duration_seconds"),
                "error":            job.get("error"),
            }
            if job["status"] == "done":
                result["image_url"] = f"{API_URL}/images/{job['job_id']}"
            return ok(result)

        elif name == "get_image_url":
            job = _get(f"/jobs/{arguments['job_id']}")
            if job["status"] != "done":
                return err(f"Job is not done yet (status: {job['status']})")
            return ok({
                "job_id":   job["job_id"],
                "image_url": f"{API_URL}/images/{job['job_id']}",
                "duration_seconds": job.get("duration_seconds"),
            })

        elif name == "list_characters":
            chars = _get("/characters")
            return ok(chars)

        elif name == "preview_prompt":
            scene = arguments.get("scene", "S1")
            extra = urllib.parse.quote(arguments.get("extra", ""))
            url   = f"{API_URL}/characters/{arguments['character']}/preview?scene={scene}&extra={extra}"
            req   = urllib.request.Request(url, data=b"", method="POST")
            with urllib.request.urlopen(req, timeout=10) as r:
                result = json.loads(r.read())
            return ok(result)

        elif name == "list_jobs":
            params = []
            if arguments.get("status"):
                params.append(f"status={arguments['status']}")
            if arguments.get("character"):
                params.append(f"character={arguments['character']}")
            qs = "?" + "&".join(params) if params else ""
            jobs = _get(f"/jobs{qs}")
            return ok(jobs)

        elif name == "health_check":
            h = _get("/health")
            return ok(h)

        else:
            return err(f"Unknown tool: {name}")

    except urllib.error.HTTPError as e:
        return err(f"API error {e.code}: {e.read().decode()[:200]}")
    except Exception as e:
        return err(str(e))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
async def main():
    async with stdio_server() as (r, w):
        await server.run(r, w, server.create_initialization_options())

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
