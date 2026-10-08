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
  --port 8000 \
  --tp-size 1 \
  --mem-fraction-static 0.88 \
  --context-length 1010000 \
  --json-model-override-args '{"text_config":{"rope_parameters":{"mrope_interleaved":true,"mrope_section":[11,11,10],"rope_type":"yarn","rope_theta":10000000,"partial_rotary_factor":0.25,"factor":4.0,"original_max_position_embeddings":262144}}}'
