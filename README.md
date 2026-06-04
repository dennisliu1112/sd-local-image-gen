# Amazing image Generator (AiG) — 本地 AI 生圖

> 完全離線、不需訂閱、不需雲端的本地 AI 生圖工具。以 [Z-Image-Turbo](https://huggingface.co/leejet/Z-Image-Turbo-GGUF) + [stable-diffusion.cpp](https://github.com/leejet/stable-diffusion.cpp) 為核心。
>
> Fully offline, no subscription, no cloud. Powered by Z-Image-Turbo + stable-diffusion.cpp.

---

## 兩種使用方式 / Two ways to use it

這個專案提供**兩種獨立的使用方式**,兩者都支援、可並存。你可以只用其中一種,也可以都用。

This project ships **two independent interfaces** — both are supported and can coexist.

| | ① 桌面 App（一般使用者）| ② MCP / REST API（AI Agent / 開發者）|
|---|---|---|
| 對象 | 用滑鼠點的人 | Claude / OpenClaw 等 AI Agent、程式呼叫 |
| 安裝 | 下載安裝檔,一鍵安裝 | 手動放引擎+模型、`pip install`、啟動伺服器 |
| 介面 | 圖形視窗 | REST API + MCP,**含角色預設系統** |
| 對應檔案 | `electron/`、`windows-app/server.py` | `sd_api.py`、`sd_mcp.py` |

> 兩者底層都呼叫同一個 `sd-server`(stable-diffusion.cpp)推論引擎,但它們是**各自獨立的伺服器**——桌面 app 沒有角色預設與 MCP;舊的 API 沒有圖形介面。

---

# 第①篇：桌面 App / Desktop App

> 給一般使用者。下載、安裝、生圖,不用碰指令。

## 下載安裝 / Download & Install

到 [**Releases 頁面**](https://github.com/dennisliu1112/sd-local-image-gen/releases) 下載對應你系統的安裝檔(**不是** Source code):

| 系統 | 檔案 |
|------|------|
| Windows (x64) | `Amazing image Generator-Setup-<版本>.exe` |
| macOS (Apple Silicon / arm64) | `Amazing image Generator-<版本>-mac-arm64.dmg` |

- **Windows**:雙擊安裝程式,固定安裝到 `C:\AiG`。若跳「Windows 已保護你的電腦 / 不明發行者」(因未購買簽章憑證),點「**其他資訊 → 仍要執行**」。
- **macOS**:打開 dmg、把 app 拖到「應用程式」。首次啟動 Gatekeeper 會擋未簽章 app → **對 app 按右鍵 → 打開 → 打開**(只需一次)。

## 首次執行 / First run

App 打開後會引導你準備兩樣東西(都在沙盒外的資料目錄,**更新版本不會被刪**):

1. **執行引擎**:點主按鈕下載「通用引擎(CPU,相容所有電腦,約 80MB)」。NVIDIA 顯卡可再加裝 CUDA 加速。(macOS 內建 Metal 引擎,免下載)
2. **AI 模型**(約 6.4GB,首次需網路):擴散模型 + VAE + 文字編碼器,會自動下載。

資料存放位置:

| 系統 | 模型/引擎/設定/紀錄 |
|------|------|
| Windows | `C:\AiG-data\`(models / engine-* / config.json / logs)|
| macOS | `~/Library/Application Support/Amazing image Generator/data/` |

生成的圖片預設存到「圖片資料夾 / AiG」(可在設定更改)。

## 運算裝置 / Engine selection

設定 → 運算裝置,預設「**自動**」即可:

- 有 **NVIDIA + CUDA** → 用 CUDA(最快)
- **macOS** → 用 Metal(Apple GPU)
- 其他(無獨顯 / Intel / AMD)→ 自動用 **CPU**(較慢但正確)

> ⚠️ **不會自動使用 Vulkan**:Z-Image 在 Vulkan 後端會生出全白圖(stable-diffusion.cpp [#1031](https://github.com/leejet/stable-diffusion.cpp/issues/1031),官方未修),所以即使裝了 Vulkan 引擎也不會被自動選用。

## 進階設定(大型電腦解鎖)/ Advanced

> 這個 app 預設是為**小容量電腦**設計的(Q4 模型、安全解析度)。若你有高階電腦,可在 **設定 → 進階 ⚡** 突破限制:

| 進階選項 | 說明 |
|----------|------|
| **模型品質** | `Q4`(預設,小、相容所有電腦)↔ `Q8`(高品質,約 6.6GB,需更多記憶體/顯存)。切換後到「模型」區塊下載對應檔即可。 |
| **自訂解析度** | 解除一般上限,最高可到 **8192px**(8K 等級)。需要極大顯存/記憶體。**若生圖失敗,會自動改用 1024×1024 重試一次**(進階失敗就降級,不會整個卡死)。 |

⚠️ 進階選項在一般電腦上可能變很慢、生圖失敗或閃退——預設值對小電腦最安全。

## 從原始碼建置 / Build from source

- **Windows**:`./build_windows.ps1` → 產出 NSIS 安裝程式。詳見 [electron/BUILD_WINDOWS.md](electron/BUILD_WINDOWS.md)。
- **macOS**:`./build_macos.sh`(需 Apple Silicon Mac + Metal 版 sd-server)→ 產出 dmg。詳見 [electron/MACOS_BUILD_TODO.md](electron/MACOS_BUILD_TODO.md)。

發版:升 `electron/package.json` 版本 → `git tag vX.Y.Z && git push origin vX.Y.Z`,CI 自動建置 Windows `.exe` 並發布到 Releases(macOS `.dmg` 目前為本機建置後手動上傳)。

---

# 第②篇：MCP / REST API（AI Agent / 開發者）

> 給 AI Agent(Claude、OpenClaw 等)程式化生圖,或想用 REST API 串接、需要**角色預設系統**的進階使用者。這是手動設定的路徑,桌面 app 不含這些能力。

## 設定 / Setup

```bash
# 1. 推論引擎:從 stable-diffusion.cpp releases 下載,或自行編譯,放到
#    src/build/bin/sd-server(.exe)。詳見下方「模型與引擎」。
# 2. 模型:下載三個模型檔放入 models/(見下表)
# 3. 角色定義(可選):
cp sd_characters.example.py sd_characters.py   # 編輯成你自己的角色
# 4. Python 套件:
pip install -r requirements_api.txt
# 5. 啟動 REST API 伺服器:
./start_api.sh        # 或 Windows: start_api.bat
# 6. 驗證:瀏覽器開 http://localhost:8080/health
```

> 不設定角色也能用,直接傳 `prompt` 參數即可。

## MCP Server 設定 / MCP configuration

讓 Claude Code / OpenClaw 直接呼叫生圖。先確保 `sd_api.py` 已啟動,再加入 MCP client 設定:

```json
{
  "mcpServers": {
    "sd-image-gen": {
      "command": "python",
      "args": ["/path/to/sd-local-image-gen/sd_mcp.py"],
      "env": { "SD_API_URL": "http://localhost:8080" }
    }
  }
}
```

> 把 `/path/to/sd-local-image-gen` 換成你的實際路徑(Windows 可用正斜線)。

**可用工具**:`generate_image`、`get_job_status`、`get_image_url`、`list_characters`、`preview_prompt`、`list_jobs`、`health_check`。

**REST 端點**:`POST /generate`、`GET /jobs/{id}`、`GET /jobs`、`GET /images/{id}`、`DELETE /jobs/{id}`、`GET /characters`、`GET /health`。

---

## 模型與引擎 / Models & engine

前往各連結同意授權後下載,放入模型資料夾(桌面 app 會自動下載;手動路徑放入 `models/`):

| 檔案 | 角色 | 來源 | 授權 |
|------|------|------|------|
| `z_image_turbo-Q4_K.gguf`（或 Q8) | 擴散模型(畫師)| [leejet/Z-Image-Turbo-GGUF](https://huggingface.co/leejet/Z-Image-Turbo-GGUF) | Apache 2.0 |
| `ae.safetensors` | VAE(解碼成圖)| [Comfy-Org/z_image_turbo](https://huggingface.co/Comfy-Org/z_image_turbo) | Apache 2.0 |
| `Qwen3-4B-Q4_K_M.gguf` | 文字編碼(讀懂 prompt)| [unsloth/Qwen3-4B-Instruct-2507-GGUF](https://huggingface.co/unsloth/Qwen3-4B-Instruct-2507-GGUF) | Apache 2.0 |

**生圖管線**:① 文字編碼(Qwen LLM)→ ② 擴散取樣(Z-Image-Turbo,4 步)→ ③ VAE 解碼成像素。三個模型接力完成一張圖。

**引擎(stable-diffusion.cpp)**:同一份 C++ 原始碼,各平台需各自編譯——Windows 為 `sd-server.exe`(CPU/CUDA),macOS 為 `sd-server`(Metal)。Windows 從原始碼編譯參考 `build_sd.example.bat`(需 VS 2022 Build Tools + CUDA 12.x)。

## 環境需求 / Requirements

| | Windows | macOS | Linux |
|---|---|---|---|
| 桌面 App | ✅ x64 | ✅ Apple Silicon | — |
| MCP/API | ✅ Python 3.10+ | ✅ Python 3.10+ | ✅ Python 3.10+ |
| 加速(可選)| NVIDIA CUDA 12.x | Metal(內建)| NVIDIA CUDA 12.x |
| 磁碟 | ~10 GB | ~10 GB | ~10 GB |

## 授權 / License

程式碼為 MIT(見 [LICENSE](LICENSE))。模型各自為 Apache 2.0,可商用(需保留授權聲明)。模型檔不含於本 repo,請自行下載並同意各自授權。角色定義(`sd_characters.py`)為私有,不含於本 repo。
