#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [ ! -f .venv-linux/bin/activate ]; then
  echo "Run scripts/setup-linux-runtimes.sh before launching SGLang." >&2
  exit 1
fi
source .venv-linux/bin/activate
exec python -m sglang.launch_server \
  --model-path Qwen/Qwen3.5-9B \
  --port 8000 \
  --tp-size 1 \
  --mem-fraction-static 0.82 \
  --context-length 262144 \
  --reasoning-parser qwen3 \
  --speculative-algo NEXTN \
  --speculative-num-steps 3 \
  --speculative-num-draft-tokens 4
