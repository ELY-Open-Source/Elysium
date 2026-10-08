#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [ ! -f .venv-linux-vllm/bin/activate ]; then
  echo "Run scripts/setup-linux-runtimes.sh before launching vLLM." >&2
  exit 1
fi
source .venv-linux-vllm/bin/activate
exec python -m vllm.entrypoints.openai.api_server \
  --model Qwen/Qwen3.5-9B \
  --host 127.0.0.1 \
  --port 8001 \
  --max-model-len 1010000 \
  --enable-prefix-caching \
  --gpu-memory-utilization 0.88 \
  --trust-remote-code \
  --rope-scaling '{"rope_type":"yarn","factor":4.0,"original_max_position_embeddings":262144}'
