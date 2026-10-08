#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [ -z "${ELY_EYE_GGUF_MODEL:-}" ]; then
  echo "Set ELY_EYE_GGUF_MODEL to the absolute GGUF model path." >&2
  exit 1
fi
server="${LLAMA_CPP_SERVER:-llama-server}"
if ! command -v "$server" >/dev/null 2>&1; then
  echo "llama-server executable is missing. Build llama.cpp or set LLAMA_CPP_SERVER." >&2
  exit 1
fi
exec "$server" \
  --model "$ELY_EYE_GGUF_MODEL" \
  --host 127.0.0.1 \
  --port 8003 \
  --ctx-size 262144 \
  --flash-attn \
  --cache-type-k q4_0 \
  --cache-type-v q4_0
