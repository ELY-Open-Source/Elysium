#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [ ! -f .venv-linux/bin/activate ]; then
  echo "Run scripts/setup-linux-runtimes.sh before launching SGLang." >&2
  exit 1
fi
source .venv-linux/bin/activate
export SGLANG_ALLOW_OVERWRITE_LONGER_CONTEXT_LEN=1
exec python -m sglang.launch_server \
  --model-path Qwen/Qwen3.5-9B \
  --port 8002 \
  --context-length 1010000 \
  --kt-cpuinfer 16 \
  --cpu-offload-gb 48
