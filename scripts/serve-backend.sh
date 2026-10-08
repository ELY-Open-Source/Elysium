#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
exec .venv/bin/ely-eye serve --host 127.0.0.1 --port 8765
