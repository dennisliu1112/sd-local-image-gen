#!/bin/bash
# ============================================================
# run_test.sh — Quick test: does image generation work?
# ============================================================
#
# This script calls the AI engine (sd) DIRECTLY to generate
# one test image. It does NOT go through the API server —
# use this to verify your binary and models are working
# before starting the full API stack.
#
# What you need before running:
#   1. sd binary in src/build/bin/  (built from source)
#   2. Models downloaded to models/
#      (see README.md → Download Models)
#
# Output: eval/local_test.png
# Log:    test_out.log
# ============================================================

ROOT="$(cd "$(dirname "$0")" && pwd)"
EXE="$ROOT/src/build/bin/sd"
DIFF="$ROOT/models/z_image_turbo-Q4_K.gguf"
VAE="$ROOT/models/ae.safetensors"
LLM="$ROOT/models/Qwen3-4B-Q4_K_M.gguf"
OUT="$ROOT/eval"
LOG="$ROOT/test_out.log"

mkdir -p "$OUT"

echo "Generating test image..."
echo "This takes 20-40 minutes. Please wait."
echo ""

echo "START: $(date)" | tee "$LOG"
"$EXE" \
  --diffusion-model "$DIFF" --vae "$VAE" --llm "$LLM" \
  --vae-tiling --offload-to-cpu \
  --steps 4 --cfg-scale 1.0 -W 1024 -H 1024 \
  -p "1girl, masterpiece, 8k, photorealistic, beach, golden hour, cinematic lighting" \
  -o "$OUT/local_test.png" \
  2>&1 | tee -a "$LOG"
echo "END: $(date)" | tee -a "$LOG"

echo ""
echo "Done! Check eval/local_test.png for the result."
echo "If no image appeared, check test_out.log for errors."
