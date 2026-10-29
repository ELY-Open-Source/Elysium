#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [ ! -f .venv-linux-vllm/bin/activate ]; then
  echo "Run scripts/setup-linux-runtimes.sh before launching vLLM." >&2
  exit 1
fi
source .venv-linux-vllm/bin/activate
# FlashInfer's sampler compiles with nvcc at first request; the PyTorch sampler needs no CUDA toolkit.
export VLLM_USE_FLASHINFER_SAMPLER=0
exec python -m vllm.entrypoints.openai.api_server \
  --model "${ELYSIUM_MODEL_DIR:-Qwen/Qwen3.5-9B}" \
  --served-model-name Qwen/Qwen3.5-9B \
  --host 127.0.0.1 \
  --port 8001 \
  --max-model-len 16384 \
  --quantization fp8 \
  --enable-prefix-caching \
  --gpu-memory-utilization 0.90 \
  --reasoning-parser qwen3
