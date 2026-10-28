#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
.venv/bin/python -m compileall ./backend/src
.venv/bin/elysium status
(cd frontend && npm run build)
