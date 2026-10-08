#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
for model in Qwen/Qwen3.5-9B Qwen/Qwen3.5-0.8B Qwen/Qwen3-VL-Embedding-8B; do
  .venv/bin/python ./scripts/download_models.py --model "$model"
done
