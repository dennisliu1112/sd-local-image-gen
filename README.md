# SD_Windows — Local Stable Diffusion API & OpenClaw Skill
### 本地 Stable Diffusion API 與 OpenClaw Skill 套件

> Offline image generation powered by [stable-diffusion.cpp](https://github.com/leejet/stable-diffusion.cpp) + Z-Image-Turbo, wrapped into a REST API and an [OpenClaw](https://openclaw.ai) skill.
>
> 基於 stable-diffusion.cpp 與 Z-Image-Turbo 的離線生圖引擎，封裝為 REST API 及 OpenClaw Skill 模組。

---

## How It Works / 這是什麼？

> **New to AI tools? / AI 新手？** Start here. / 先看這裡。

This project lets your computer generate images using AI — fully offline, no subscription, no cloud.

這個專案讓你的電腦在完全離線的情況下用 AI 生圖，不需要訂閱、不需要雲端服務。

**Three pieces, stacked on top of each other / 三層架構：**

```
You / Your AI Agent          ← sends requests, checks progress
         ↕  HTTP
    sd_api.py                ← manages the job queue (this repo)
         ↕  internal
   sd-server(.exe)           ← the AI engine that draws the image
```

**Why does it take 20–40 minutes?**
Generating a 1024×1024 image requires billions of math operations, even with a GPU. This is normal for local inference — cloud services feel instant because they use dozens of GPUs in parallel.

**為什麼要 20–40 分鐘？**
生成一張 1024×1024 的圖需要數十億次運算，即使有 GPU 也需要時間。雲端服務感覺很快，是因為他們同時用了幾十張顯卡。

**Why does it return a `job_id` instead of the image directly?**
Because 20–40 minutes is too long to wait in one connection. You submit a job → get an ID → come back later to download the result. Your app (or AI agent) is never blocked.

**為什麼不直接回傳圖片，要用 `job_id`？**
因為 20–40 分鐘太長，連線會超時。送出任務後先拿到 ID，之後再回來下載結果。你的程式或 AI Agent 不會被卡住。

---

## Let an AI Agent Install This For You / 讓 AI 幫你安裝

Not sure where to start? Copy the prompt below and paste it to Claude, ChatGPT, or any AI assistant. It will guide you through the entire setup.

不知道從哪裡開始？把下面的提示詞複製給 Claude、ChatGPT 或任何 AI 助理，它會帶你完成整個安裝流程。

**English:**

```
I want to set up the SD_Windows local image generation project on my computer.
The README is at: https://github.com/[your-repo]/SD_Windows

Please help me:
1. Check if my system meets the requirements (Windows 10/11, NVIDIA GPU, CUDA 12.x, Python 3.10+)
2. Download the sd-server binary from stable-diffusion.cpp releases and place it in the right folder
3. Download the three required model files from Hugging Face and place them in models\
4. Copy sd_characters.example.py to sd_characters.py
5. Install Python dependencies with: pip install -r requirements_api.txt
6. Start the API server with: start_api.bat
7. Verify it works by opening http://localhost:8080/health in a browser

Please check each step and tell me if anything is missing or if I hit an error.
```

**中文：**

```
我想在我的電腦上安裝 SD_Windows 本地 AI 生圖專案。
README 在這裡：https://github.com/[your-repo]/SD_Windows

請幫我完成以下步驟：
1. 確認我的電腦符合需求（Windows 10/11、NVIDIA 顯卡、CUDA 12.x、Python 3.10 以上）
2. 從 stable-diffusion.cpp 的 releases 頁面下載 sd-server 執行檔，放到正確的資料夾
3. 從 Hugging Face 下載三個模型檔案，放到 models\ 資料夾
4. 把 sd_characters.example.py 複製一份，改名為 sd_characters.py
5. 執行 pip install -r requirements_api.txt 安裝 Python 套件
6. 執行 start_api.bat 啟動 API 伺服器
7. 在瀏覽器開啟 http://localhost:8080/health，確認出現正常回應

請一步一步帶我完成，遇到錯誤時告訴我怎麼解決。
```

---

## Features / 功能特點

| | EN | 中文 |
|---|---|---|
| 🖥️ | Fully offline, no API key needed | 完全離線，不需要 API 金鑰 |
| ⚡ | CUDA GPU acceleration | CUDA GPU 加速 |
| 🔌 | REST API with async job queue | 非同步 REST API |
| 🎭 | Character preset system | 可擴充的角色預設系統 |
| 🤖 | OpenClaw skill integration | OpenClaw Skill 整合 |
| 🧩 | MCP server for AI agents (Claude, OpenClaw) | MCP Server 供 AI Agent 直接呼叫 |
| 🔒 | Your characters stay private | 角色定義完全私有，不含於此 repo |

---

## Requirements / 環境需求

| | Windows | Linux (Ubuntu) |
|---|---|---|
| OS | Windows 10/11 | Ubuntu 20.04+ |
| GPU | NVIDIA CUDA 12.x | NVIDIA CUDA 12.x |
| Python | 3.10+ | 3.10+ |
| Binary | `sd-server.exe` | `sd-server` |
| Disk | ~10 GB | ~10 GB |

> The Python scripts (API server, skill, test) are fully cross-platform. Only the inference binary differs.
> Python 腳本完全跨平台，僅推理執行檔因 OS 不同而有差異。

---

## Setup / 安裝步驟

### 1. Inference Engine / 推理引擎

Download from [stable-diffusion.cpp releases](https://github.com/leejet/stable-diffusion.cpp/releases) or build from source.

從 [stable-diffusion.cpp releases](https://github.com/leejet/stable-diffusion.cpp/releases) 下載，或自行從原始碼編譯。

**Windows** — place files at / 放置路徑：
```
src\build\bin\sd-server.exe
src\build\bin\cublas64_12.dll
src\build\bin\cublasLt64_12.dll
src\build\bin\cudart64_12.dll
```

To build from source on Windows, copy `build_sd.example.bat` to `build_sd.bat`, adjust the paths inside, then run it. Requires Visual Studio 2022 Build Tools and CUDA Toolkit 12.x.

Windows 從原始碼編譯：將 `build_sd.example.bat` 複製為 `build_sd.bat`，修改其中的路徑後執行。需要 Visual Studio 2022 Build Tools 和 CUDA Toolkit 12.x。

**Linux (Ubuntu)** — build from source / 從原始碼編譯：
```bash
sudo apt install cmake ninja-build
git clone https://github.com/leejet/stable-diffusion.cpp
cd stable-diffusion.cpp && mkdir build && cd build
cmake .. -G Ninja -DGGML_CUDA=ON -DCMAKE_BUILD_TYPE=Release
ninja
# Copy binary / 複製執行檔：
cp bin/sd-server /path/to/SD_Windows/src/build/bin/sd-server
```

### 2. Download Models / 下載模型

Visit each link, agree to the license, and place files in `models\`.

前往各連結，同意授權後下載，放入 `models\` 目錄。

| File / 檔案 | Role / 用途 | Source / 來源 | License / 授權 |
|---|---|---|---|
| `z_image_turbo-Q4_K.gguf` | Diffusion model / 生圖主模型 | [leejet/Z-Image-Turbo-GGUF](https://huggingface.co/leejet/Z-Image-Turbo-GGUF) | Apache 2.0 |
| `ae.safetensors` | VAE decoder | [black-forest-labs/FLUX.1-schnell](https://huggingface.co/black-forest-labs/FLUX.1-schnell/tree/main) | Apache 2.0 |
| `Qwen3-4B-Q4_K_M.gguf` | LLM prompt enhancer / prompt 增強 | [Qwen/Qwen3-4B-GGUF](https://huggingface.co/Qwen/Qwen3-4B-GGUF) | Apache 2.0 |

> Model files are not included in this repository. Each must be downloaded and agreed to individually.
> 模型檔案不包含於此 repo，請自行下載並同意各自授權。

### 3. Character Definitions / 角色定義

```bash
cp sd_characters.example.py sd_characters.py
# Edit sd_characters.py to define your own characters
# 編輯 sd_characters.py，填入你自己的角色設定
```

The API and skill work without characters too — use raw `prompt` instead.

不設定角色也可以正常使用，直接傳 `prompt` 參數即可。

### 4. Install Python Dependencies / 安裝 Python 套件

```bash
pip install -r requirements_api.txt
```

---

## Usage / 使用方式

### Quick Test / 快速測試

```bash
# Windows
run_test.bat

# Linux / macOS
chmod +x run_test.sh && ./run_test.sh
```

### Benchmark (Windows only)

```bat
run_bench.bat    # 5 images / 5 張
run_bench2.bat   # 12 images / 12 張
```

### REST API Server / REST API 伺服器

```bash
# Windows
start_api.bat        # foreground / 前台
start_api_bg.bat     # background / 背景常駐

# Linux / macOS
chmod +x start_api.sh && ./start_api.sh
# or background / 或背景執行：
nohup ./start_api.sh &
```

Swagger UI: `http://localhost:8080/docs`

```bash
# List character presets / 列出角色預設
curl http://localhost:8080/characters

# Generate by character / 用角色預設生圖
curl -X POST http://localhost:8080/generate \
  -H "Content-Type: application/json" \
  -d '{"character": "character1", "scene": "S1"}'

# Generate with custom prompt / 自訂 prompt 生圖
curl -X POST http://localhost:8080/generate \
  -H "Content-Type: application/json" \
  -d '{"prompt": "1girl, beach, golden hour, photorealistic"}'

# Check status / 查詢狀態
curl http://localhost:8080/jobs/{job_id}

# Download image / 下載圖片
curl http://localhost:8080/images/{job_id} -o result.png
```

### Character Test / 角色測試

```bash
python test_characters.py
# Output: eval\characters\
```

---

## OpenClaw Skill

Copy `sd-local-image-gen/` to your OpenClaw skills directory.

將 `sd-local-image-gen/` 複製到 OpenClaw 的 skills 目錄。

**Start the API server first** (see above), then set:

先啟動 API 伺服器（見上方說明），再設定環境變數：

```bash
# Windows
set SD_API_URL=http://localhost:8080

# macOS / Linux
export SD_API_URL=http://localhost:8080
```

The skill communicates with `sd_api.py` via HTTP — the agent session is never blocked by long generation.

Skill 透過 HTTP 與 `sd_api.py` 溝通，生圖為非同步任務，Agent session 不會被卡住。

```bash
# List characters / 列出角色
python {skillDir}/scripts/gen.py --list-characters

# Submit job — returns job_id immediately / 送出任務，立即回傳 job_id
python {skillDir}/scripts/gen.py --character character1 --scene S1

# Check status / 查詢進度
python {skillDir}/scripts/gen.py --status {job_id}

# Collect (download) completed image / 下載完成的圖片
python {skillDir}/scripts/gen.py --collect {job_id} --out-dir ./output

# Custom prompt / 自訂 prompt
python {skillDir}/scripts/gen.py --prompt "1girl, beach, golden hour"
```

> Generation takes **20–40 min** per image. Agents must **submit → end session → check later**.
> 生圖約需 20–40 分鐘，Agent 應送出後立即結束 session，稍後再查詢狀態。

---

## MCP Server / MCP 伺服器

> **Who needs this?** Only if you use an AI agent that supports the MCP protocol (e.g. Claude Code, OpenClaw). If you just want to generate images via curl or the REST API, skip this section entirely.
>
> **誰需要這個？** 只有在使用支援 MCP 協定的 AI Agent（如 Claude Code、OpenClaw）時才需要。如果你只是要直接呼叫 REST API 或用 curl 生圖，可以直接跳過這一節。

`sd_mcp.py` lets an AI agent call image generation directly — without you having to write any curl commands. The agent submits jobs, polls status, and retrieves images on its own.

`sd_mcp.py` 讓 AI Agent 可以直接呼叫生圖功能，不需要你手動下指令。Agent 會自行送出任務、查詢進度、取回圖片。

### Prerequisites / 前置條件

The REST API server (`sd_api.py`) must be running before the MCP server can process requests.

MCP server 在收到請求時會呼叫 REST API，因此 `sd_api.py` 必須先啟動。

### Configuration / 設定

Add to your MCP client config (Claude Code `~/.claude/settings.json`, or OpenClaw MCP settings):

加入你的 MCP client 設定（Claude Code `~/.claude/settings.json` 或 OpenClaw MCP 設定）：

```json
{
  "mcpServers": {
    "sd-image-gen": {
      "command": "python",
      "args": ["/path/to/SD_Windows/sd_mcp.py"],
      "env": {
        "SD_API_URL": "http://localhost:8080"
      }
    }
  }
}
```

> Replace `/path/to/SD_Windows` with the actual path to your installation. On Windows use forward slashes (e.g. `C:/Users/you/SD_Windows`).
> 將 `/path/to/SD_Windows` 替換為你的實際安裝路徑。Windows 可使用正斜線（如 `C:/Users/you/SD_Windows`）。

### Available Tools / 可用工具

| Tool / 工具 | Description / 說明 |
|---|---|
| `generate_image` | Submit a generation job; returns `job_id` immediately |
| `get_job_status` | Poll job progress: `pending → running → done / failed` |
| `get_image_url` | Get download URL for a completed image |
| `list_characters` | List all character presets and their scenes |
| `preview_prompt` | Preview the assembled prompt for a character+scene (no generation) |
| `list_jobs` | List recent jobs, optionally filtered by status or character |
| `health_check` | Check if API server and sd-server inference engine are ready |

### Typical Agent Workflow / 典型 Agent 流程

```
1. health_check           → confirm server is ready
2. list_characters        → pick character + scene
3. generate_image(...)    → receive job_id
4. [end turn / wait]      → do NOT poll in a loop within one session
5. get_job_status(job_id) → check in a later session
6. get_image_url(job_id)  → retrieve the image URL when done
```

---

## API Reference / API 端點

| Method | Path | Description / 說明 |
|---|---|---|
| `POST` | `/generate` | Submit job / 提交任務 |
| `GET` | `/jobs/{id}` | Job status / 查詢狀態 |
| `GET` | `/jobs` | List jobs / 列出任務（支援 `?status=` `?character=`）|
| `GET` | `/images/{id}` | Download image / 下載圖片 |
| `DELETE` | `/jobs/{id}` | Delete job / 刪除任務 |
| `GET` | `/characters` | List presets / 列出角色 |
| `GET` | `/characters/{id}` | Character detail / 角色詳情 |
| `POST` | `/characters/{id}/preview` | Preview prompt / 預覽 prompt |
| `GET` | `/health` | Health check / 健康檢查 |

### Generation Parameters / 生圖參數

| Parameter / 參數 | Default / 預設 | Description / 說明 |
|---|---|---|
| `steps` | `4` | Diffusion steps (4 recommended for turbo) / 擴散步數（Turbo 模型建議 4 步） |
| `cfg_scale` | `1.0` | CFG guidance scale / 引導強度 |
| `width` / `height` | `1024` | Output resolution / 輸出解析度 |
| `seed` | `-1` | Random seed, -1 = random / 隨機種子，-1 為隨機 |

---

## Character System / 角色系統

Define your own characters in `sd_characters.py` (not included, private).
See `sd_characters.example.py` for the format.

角色定義儲存於 `sd_characters.py`（私有，不含於此 repo）。
格式參考 `sd_characters.example.py`。

```python
CHARACTERS = {
    "mychar": {
        "name": "My Character",
        "emoji": "🌸",
        "description": "vibe description",
        "base": "hair, style, personality tags...",
        "scenes": {
            "S1": {"name": "Scene 1", "prompt": "..."},
            "S2": {"name": "Scene 2", "prompt": "..."},
            "S3": {"name": "Scene 3", "prompt": "..."},
        },
    }
}
```

---

## Project Structure / 專案結構

```
SD_Windows/
├── sd_api.py                  # REST API server (FastAPI + async job queue)
├── sd_mcp.py                  # MCP server (exposes tools to AI agents)
├── sd_characters.example.py   # Character template / 角色範本
├── sd_characters.py           # Your characters (private / 私有，不進 Git)
├── test_characters.py         # Character test script
├── requirements_api.txt       # Python dependencies
├── start_api.bat / .sh        # Start API server (foreground)
├── start_api_bg.bat           # Start API server (background, Windows)
├── sd-local-image-gen/        # OpenClaw skill
│   ├── SKILL.md
│   └── scripts/gen.py         # CLI client for sd_api.py
├── src/build/bin/             # Inference engine (not in Git / 不進 Git)
│   ├── sd-server.exe / sd-server
│   └── *.dll                  # CUDA runtime (Windows)
├── models/                    # Model files (not in Git / 不進 Git)
└── eval/                      # Generated images (not in Git / 不進 Git)
```

---

## License / 授權

### This project / 本專案程式碼

**MIT License** — free to use, modify, and distribute, including commercially.
**MIT 授權** — 可自由使用、修改、商業發布。

### Third-party models / 第三方模型（需自行下載）

| Component / 元件 | License / 授權 |
|---|---|
| [stable-diffusion.cpp](https://github.com/leejet/stable-diffusion.cpp) | MIT |
| [Z-Image-Turbo](https://huggingface.co/leejet/Z-Image-Turbo-GGUF) | Apache 2.0 |
| [FLUX.1-schnell VAE](https://huggingface.co/black-forest-labs/FLUX.1-schnell) | Apache 2.0 |
| [Qwen3-4B](https://huggingface.co/Qwen/Qwen3-4B-GGUF) | Apache 2.0 |

All third-party models are Apache 2.0 — commercial use permitted with attribution.
所有第三方模型均為 Apache 2.0 授權，允許商業使用，須保留來源標註。

> Model files are **not included** in this repository. Download and agree to each license separately.
> 模型檔案**不含於**此 repo，請自行前往各連結下載並同意授權。
