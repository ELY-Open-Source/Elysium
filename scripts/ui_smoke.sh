#!/usr/bin/env bash
set -euo pipefail

# The console is proven by driving it: a fresh home, the built interface served by the
# API itself, and a browser that searches, pages, forgets, mounts and reads adapter states.
# ELYSIUM_UI_SMOKE_KEEP=1 leaves the temporary home in place and prints it.
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python="${PYTHON:-$repo/.venv/bin/python}"
server_bin="$(dirname "$python")/elysium"
if [[ ! -x "$server_bin" ]]; then
  echo "$server_bin is not installed; run scripts/install.sh first" >&2
  exit 1
fi
port="${ELYSIUM_UI_SMOKE_PORT:-8791}"
api="http://127.0.0.1:${port}"
home="$(mktemp -d "${TMPDIR:-/tmp}/elysium-ui-smoke.XXXXXX")"
server=""

cleanup() {
  if [[ -n "$server" ]] && kill -0 "$server" 2>/dev/null; then
    kill "$server" 2>/dev/null || true
    wait "$server" 2>/dev/null || true
  fi
  if [[ "${ELYSIUM_UI_SMOKE_KEEP:-}" == "1" ]]; then
    echo "kept: $home"
  else
    rm -rf "$home"
  fi
}
trap cleanup EXIT

if [[ ! -f "$repo/frontend/dist/index.html" ]]; then
  (cd "$repo/frontend" && npm run build)
fi

export ELYSIUM_HOME="$home"
export ELYSIUM_DEFAULT_HOLDER=wife
export ELYSIUM_AUTH_TOKEN="ui-smoke-operator"
export ELYSIUM_UI_DIR="$repo/frontend/dist"

"$server_bin" serve --host 127.0.0.1 --port "$port" >"$home/serve.log" 2>&1 &
server=$!

ready=""
for _ in $(seq 1 120); do
  if curl -sf "$api/api/status" >/dev/null 2>&1; then
    ready=yes
    break
  fi
  if ! kill -0 "$server" 2>/dev/null; then
    echo "the API stopped before it was ready:" >&2
    cat "$home/serve.log" >&2
    exit 1
  fi
  sleep 0.5
done
if [[ -z "$ready" ]]; then
  echo "the API never answered on $api:" >&2
  cat "$home/serve.log" >&2
  exit 1
fi

# The interface is served by the same process, so the browser talks to one origin.
if ! curl -sf "$api/" >/dev/null 2>&1; then
  echo "the API is up but does not serve the built interface at /; is frontend/dist real?" >&2
  cat "$home/serve.log" >&2
  exit 1
fi

(cd "$repo/frontend" && ELYSIUM_API="$api" ELYSIUM_UI_URL="$api/" ELYSIUM_UI_SMOKE_DIR="$home" node scripts/verify-ui.mjs)

echo "PASS: the console searches, pages, forgets, mounts and reports adapter states"
