#!/usr/bin/env python3
"""
bench_5shots.py — 連跑 5 張小愛測試，量化本機 Apple Silicon 效能
用法：python bench_5shots.py [width] [height]  (預設 512x512)
"""

import sys, time, json
import urllib.request, urllib.error
from pathlib import Path
from datetime import datetime

API = "http://localhost:8080"
OUT = Path(__file__).parent / "eval"
OUT.mkdir(exist_ok=True)

W = int(sys.argv[1]) if len(sys.argv) > 1 else 512
H = int(sys.argv[2]) if len(sys.argv) > 2 else 512

# ── 小愛 SOUL（從 oracle-vm xiaoai_vocab.py 擷取）──────────────────────
SOUL = (
    "1girl, East Asian beauty, masterpiece, 8k, photorealistic, cinematic soft lighting, "
    "(delicate V-shaped face:1.4), (aegyo-sal:1.2), "
    "(pale porcelain skin:1.8), (cool undertones:1.7), "
    "(perfect skin texture:1.3), (natural skin tone:1.2), "
    "(K-pop idol aesthetic:1.6), (ultra-detailed face:1.5), "
    "(honey peach glossy lips:1.4), (watery peach tint:1.3), "
    "(platinum blonde silky hair:1.3), "
    "(extreme hourglass figure:1.2), (voluptuous bust:1.1), "
    "(extremely slim snatched waist:1.2), flat stomach, "
    "(graceful curves:1.3), (slim waist:1.4), (feminine silhouette:1.3), "
    "(long legs:1.4), (extra long slender legs:1.2), straight legs, thin ankles, "
    "(pure yet seductive innocence:1.3), (girlfriend material vibe:1.2), "
    "avoid yellow skin, avoid dark skin, avoid warm skin tone, avoid tanned, "
    "avoid cartoon, avoid 3d, avoid cgi, avoid rendering, avoid cg"
)

NEGATIVE = (
    "lowres, bad anatomy, bad hands, text, error, missing fingers, "
    "extra digit, fewer digits, cropped, worst quality, low quality, "
    "normal quality, jpeg artifacts, signature, watermark, username, blurry, "
    "deformed, ugly, mutated, extra limbs, bad proportions, "
    "yellow skin, dark skin, warm skin tone, tanned"
)

# ── 5 張測試場景 ─────────────────────────────────────────────────────────
SHOTS = [
    {
        "label": "S1｜熱帶海灘 · 比基尼 · 仰視",
        "scene": "standing on pristine white sand isolated tropical beach, direct harsh sunlight",
        "outfit": "minimalist high-cut black string bikini",
        "pose": "standing naturally, full body",
        "expression": "pure innocent expression, gentle smile",
        "angle": "low angle shot, looking up",
        "lighting": "direct harsh sunlight, hard shadows",
    },
    {
        "label": "S2｜臥室 · 絲滑連身裙 · 躺臥",
        "scene": "reclining on a white bed, bright sunlit modern bedroom, natural soft morning light",
        "outfit": "ultra-short black silk slip dress with spaghetti straps",
        "pose": "lying flat on back, face up, full body shot from head to toes",
        "expression": "soft seductive gaze, slightly parted lips",
        "angle": "full body front view",
        "lighting": "soft morning sunlight, warm domestic atmosphere",
    },
    {
        "label": "S3｜辦公室 · 皮裙西裝 · 站姿",
        "scene": "standing in a modern glass office terminal, high-contrast office lighting, dramatic shadows",
        "outfit": "tight black silk shirt and high-waisted black leather pencil skirt, black high heels",
        "pose": "standing naturally, full body",
        "expression": "playful sweet smile, friendly expression",
        "angle": "full body, cinematic composition",
        "lighting": "high-contrast dramatic side lighting",
    },
    {
        "label": "S4｜泳池 · 針織連身 · 坐姿撩髮",
        "scene": "standing by a luxury infinity pool, golden hour sunset, water droplets on skin",
        "outfit": "light oatmeal ribbed knit bodycon mini dress",
        "pose": "sitting gracefully, legs crossed",
        "expression": "looking back with a sweet mischievous smile",
        "angle": "half body close-up shot",
        "gesture": "hair flowing, fingers running through hair",
        "lighting": "golden hour warm lighting",
    },
    {
        "label": "S5｜溫泉 · 白衬衫 · 背面回眸",
        "scene": "in a luxurious open-air hot spring bath, misty steam, soft ambient light",
        "outfit": "oversized crisp white men's button-down shirt, only top buttons fastened, falling off one shoulder",
        "pose": "back view, looking over shoulder",
        "expression": "looking back with a sweet mischievous smile",
        "angle": "back view, looking over shoulder",
        "lighting": "warm sensual lighting, water reflections on skin",
    },
]


def build_prompt(shot: dict) -> str:
    parts = [SOUL]
    for key in ("outfit", "scene", "pose", "expression", "angle", "gesture", "lighting"):
        v = shot.get(key, "")
        if v:
            parts.append(v)
    return ", ".join(p.strip(", ") for p in parts if p)


def api(method: str, path: str, body=None):
    url = API + path
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data,
                                  headers={"Content-Type": "application/json"} if data else {},
                                  method=method)
    with urllib.request.urlopen(req, timeout=3600) as r:
        return json.loads(r.read())


def wait_done(job_id: str, label: str) -> dict:
    dots = 0
    while True:
        job = api("GET", f"/jobs/{job_id}")
        if job["status"] in ("done", "failed"):
            return job
        dots += 1
        elapsed = dots * 5
        print(f"  ⏱  {elapsed:3d}s …", end="\r", flush=True)
        time.sleep(5)


def download(job_id: str, filename: str):
    url = f"{API}/images/{job_id}"
    dest = OUT / filename
    urllib.request.urlretrieve(url, dest)
    return dest


# ── 主流程 ───────────────────────────────────────────────────────────────
def main():
    # 確認 API 健康
    health = api("GET", "/health")
    if not health.get("sd_server_ready"):
        print("❌ sd-server not ready, start the API first: ./start_api.sh")
        sys.exit(1)

    print(f"\n🎬 小愛 Bench — {W}×{H}，5 shots\n{'─'*52}")
    results = []
    wall_start = time.monotonic()

    for i, shot in enumerate(SHOTS, 1):
        prompt = build_prompt(shot)
        print(f"\n[{i}/5] {shot['label']}")
        print(f"  Prompt: {prompt[:80]}…")

        job = api("POST", "/generate", {
            "prompt": prompt,
            "negative_prompt": NEGATIVE,
            "width": W, "height": H,
            "steps": 4, "cfg_scale": 1.0,
            "seed": 1000 + i,
        })
        job_id = job["job_id"]

        t0 = time.monotonic()
        result = wait_done(job_id, shot["label"])
        elapsed = time.monotonic() - t0

        if result["status"] == "done":
            fname = f"bench_{i:02d}_{W}x{H}.png"
            dest = download(job_id, fname)
            print(f"  ✅  {elapsed:.1f}s → {dest.name}")
            results.append((shot["label"], elapsed, str(dest)))
        else:
            print(f"  ❌  failed: {result.get('error','?')}")
            results.append((shot["label"], elapsed, "FAILED"))

    wall = time.monotonic() - wall_start
    avg = sum(r[1] for r in results) / len(results)

    print(f"\n{'═'*52}")
    print(f"  總耗時：{wall:.0f}s  ·  平均每張：{avg:.1f}s  ·  {W}×{H}")
    print(f"{'─'*52}")
    for label, t, _ in results:
        print(f"  {t:5.1f}s  {label}")
    print(f"{'═'*52}\n")


if __name__ == "__main__":
    main()
