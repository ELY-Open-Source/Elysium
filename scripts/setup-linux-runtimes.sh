#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if ! command -v nvidia-smi >/dev/null 2>&1; then
  echo "nvidia-smi is missing; these runtimes need a CUDA host." >&2
  exit 1
fi
nvidia-smi -L >/dev/null
uv_bin="${ELY_EYE_UV:-$HOME/.local/bin/uv}"
if ! command -v "$uv_bin" >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
  uv_bin="$HOME/.local/bin/uv"
fi
for venv in .venv-linux .venv-linux-vllm; do
  "$uv_bin" venv "$venv" --python 3.12
done
"$uv_bin" pip install --python .venv-linux/bin/python --prerelease=allow -r backend/requirements-sglang-linux.txt
"$uv_bin" pip install --python .venv-linux-vllm/bin/python --prerelease=allow -r backend/requirements-vllm-linux.txt
"$uv_bin" pip install --python .venv-linux/bin/python --prerelease=allow -r backend/requirements-ktransformers-linux.txt
.venv/bin/ely-eye runtime-profiles
