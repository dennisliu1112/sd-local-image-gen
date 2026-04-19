---
name: sd-local-image-gen
description: Generate images locally using a compiled Stable Diffusion server (sd-server) with CUDA GPU acceleration. Submits async jobs via REST API — agent session is never blocked.
homepage: https://github.com/leejet/stable-diffusion.cpp
metadata:
  {
    "openclaw":
      {
        "emoji": "🎨",
        "requires": { "bins": ["python3"], "env": ["SD_API_URL"] },
        "primaryEnv": "SD_API_URL",
        "install":
          [
            {
              "id": "python-brew",
              "kind": "brew",
              "formula": "python",
              "bins": ["python3"],
              "label": "Install Python",
            },
            {
              "id": "sd-api-url-env",
              "kind": "env",
              "label": "SD_API_URL — URL of the SD API server (e.g. http://localhost:8080)",
            },
          ],
      },
  }
---

# sd-local-image-gen

Generate images **fully offline** using a locally compiled `sd-server` with CUDA GPU acceleration.

## Architecture / 架構

```
Agent (OpenClaw / Claude)
  ↓ exec python3 gen.py --character xiaoai --scene S1
gen.py  →  POST http://{SD_API_URL}/generate  →  returns job_id immediately
             ↓ (background, non-blocking)
         sd_api.py  →  sd-server.exe (port 8190)
             ↓ done
         Agent polls: gen.py --status {job_id}
             ↓ image ready
         gen.py downloads image → returns file path
```

> Generation takes **20–40 minutes** per image (1024×1024, local GPU).
> The agent **must not wait** — submit job and check back later.
>
> 生圖約需 20–40 分鐘，Agent 送出後應立即結束 session，稍後再查詢狀態。

---

## Prerequisites / 前置條件

### 環境變數

| Variable | Description | Example |
|---|---|---|
| `SD_API_URL` | SD API server URL | `http://localhost:8080` |

### SD API Server must be running / 必須先啟動 API Server

```bash
# Windows
start_api.bat

# Linux / macOS
./start_api.sh
```

The server auto-starts `sd-server` and manages the job queue.
啟動後會自動管理 sd-server 及 job queue。

---

## Usage / 使用方式

### Submit a job / 提交生圖任務

```bash
# By character preset
python {baseDir}/scripts/gen.py --character xiaoai --scene S1

# Custom prompt
python {baseDir}/scripts/gen.py --prompt "1girl, beach, golden hour"

# List available characters
python {baseDir}/scripts/gen.py --list-characters
```

### Check job status / 查詢進度

```bash
python {baseDir}/scripts/gen.py --status {job_id}
```

### Collect completed image / 取得完成的圖片

```bash
python {baseDir}/scripts/gen.py --collect {job_id} --out-dir /path/to/save
```

---

## Options / 參數

| Flag | Default | Description |
|---|---|---|
| `--character` | | Character preset ID |
| `--scene` | `S1` | Scene ID (S1 / S2 / S3) |
| `--prompt` | | Custom text prompt |
| `--negative-prompt` | | Negative prompt |
| `--status` | | Check job status by job_id |
| `--collect` | | Download completed image by job_id |
| `--list-characters` | | List all character presets |
| `--width` | `1024` | Image width |
| `--height` | `1024` | Image height |
| `--steps` | `4` | Diffusion steps |
| `--cfg-scale` | `1.0` | CFG guidance scale |
| `--seed` | `-1` | Random seed |
| `--out-dir` | `~/Pictures/sd-local` | Output directory |

---

## Model Downloads / 模型下載

Models are **not included**. Download separately and place in the `models/` directory.

| File | Source | License |
|---|---|---|
| `z_image_turbo-Q4_K.gguf` | [leejet/Z-Image-Turbo-GGUF](https://huggingface.co/leejet/Z-Image-Turbo-GGUF) | Apache 2.0 |
| `ae.safetensors` | [black-forest-labs/FLUX.1-schnell](https://huggingface.co/black-forest-labs/FLUX.1-schnell/tree/main) | Apache 2.0 |
| `Qwen3-4B-Q4_K_M.gguf` | [Qwen/Qwen3-4B-GGUF](https://huggingface.co/Qwen/Qwen3-4B-GGUF) | Apache 2.0 |
