#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
.venv/bin/python -m pip install --upgrade pip setuptools wheel
.venv/bin/python -m pip install -e ./backend
.venv/bin/python -m pip install --upgrade --no-cache-dir unsloth unsloth_zoo
.venv/bin/python -m pip install --upgrade --no-cache-dir --index-url https://download.pytorch.org/whl/cu130 torch==2.12.0+cu130 torchvision==0.27.0+cu130
.venv/bin/python -m pip install --upgrade --no-cache-dir transformers==5.9.0 datasets==4.8.5 dill==0.4.1 multiprocess==0.70.19 fsspec==2026.2.0 safetensors==0.8.0rc0
(cd frontend && npm install)
[ -f .env ] || cp .env.example .env
.venv/bin/elysian status
