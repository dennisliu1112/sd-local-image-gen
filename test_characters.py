"""
test_characters.py
從 sd_characters.py 讀取所有角色，每人各生一張代表場景 (預設 S1)。
輸出至 eval/characters/
"""

import io
import os
import subprocess
import sys
import time
from pathlib import Path

# Windows cp950 終端不支援 emoji，強制 UTF-8 輸出
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).parent

# 匯入角色模組
sys.path.insert(0, str(ROOT))
from sd_characters import CHARACTERS, build_prompt

EXE  = ROOT / "src" / "build" / "bin" / ("sd-cli.exe" if os.name == "nt" else "sd")
DIFF = ROOT / "models" / "z_image_turbo-Q4_K.gguf"
VAE  = ROOT / "models" / "ae.safetensors"
LLM  = ROOT / "models" / "Qwen3-4B-Q4_K_M.gguf"
OUT  = ROOT / "eval" / "characters"
LOG  = ROOT / "test_characters.log"

OUT.mkdir(parents=True, exist_ok=True)

FLAGS = ["--vae-tiling", "--offload-to-cpu", "--steps", "4", "--cfg-scale", "1.0", "-W", "1024", "-H", "1024"]

def run(char_id: str, scene_id: str = "S1") -> tuple[bool, float, str]:
    char   = CHARACTERS[char_id]
    prompt = build_prompt(char_id, scene_id)
    output = OUT / f"{char_id}_{scene_id}.png"

    cmd = [
        str(EXE),
        "--diffusion-model", str(DIFF),
        "--vae", str(VAE), "--llm", str(LLM),
        *FLAGS,
        "-p", prompt,
        "-o", str(output),
    ]
    t0 = time.monotonic()
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        elapsed = round(time.monotonic() - t0, 1)
        ok = result.returncode == 0 and output.exists()
        log = result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        return False, 600.0, "Timeout"
    except Exception as e:
        return False, 0.0, str(e)
    return ok, elapsed, log

def main():
    # 前置檢查
    missing = [str(p) for p in [EXE, DIFF, VAE, LLM] if not p.exists()]
    if missing:
        print("ERROR: 缺少必要檔案，請先執行 sync_from_oracle.bat")
        for m in missing:
            print(f"  MISS: {m}")
        sys.exit(1)

    total = len(CHARACTERS)
    print(f"=== Characters Test ({total} 角色) ===\n")
    log_lines = []
    ok_count  = 0

    for i, (cid, char) in enumerate(CHARACTERS.items(), 1):
        label = f"[{i}/{total}] {char['emoji']} {char['name']} (S1: {char['scenes']['S1']['name']})"
        print(f"{label}  生成中...", end=" ", flush=True)

        ok, elapsed, log = run(cid, "S1")
        if ok:
            ok_count += 1
            print(f"OK  {elapsed}s  ->  eval/characters/{cid}_S1.png")
        else:
            print(f"FAIL")
            print(f"  {log[-200:]}", flush=True)

        log_lines.append(f"--- {label} ---\n{'OK' if ok else 'FAIL'} {elapsed}s\n{log[-300:]}\n")

    print(f"\n完成：{ok_count}/{total} 張成功")
    print(f"輸出：{OUT}")
    LOG.write_text("\n".join(log_lines), encoding="utf-8")

if __name__ == "__main__":
    main()
