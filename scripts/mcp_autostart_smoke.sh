#!/usr/bin/env bash
# Prove a client needs nothing running: after `elysian init`, the MCP server starts the API itself.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
home="$(mktemp -d)"
port="${PORT:-8797}"
export ELYSIAN_HOME="$home/.elysian"
export ELYSIAN_API="http://127.0.0.1:${port}"
unset ELYSIAN_AUTH_TOKEN
export PATH="$root/.venv/bin:$PATH"

cleanup() {
  if [ -f "$home/mcp.err" ]; then
    pid="$(sed -n 's/.*(pid \([0-9]*\)).*/\1/p' "$home/mcp.err" | head -n 1)"
    if [ -n "$pid" ]; then kill "$pid" 2>/dev/null || true; fi
  fi
  rm -rf "$home"
}
trap cleanup EXIT

if curl -sf "${ELYSIAN_API}/api/status" >/dev/null 2>&1; then
  echo "FAIL: port ${port} already answers; the MCP server would find that API instead of starting one. Run with PORT=<free port>."
  exit 1
fi

elysian init >/dev/null
(cd "$root/elysian-mcp" && go build -o "$home/elysian-mcp" ./cmd/elysian-mcp)

python3 "$root/scripts/mcp_roundtrip.py" "$home/elysian-mcp" "$home/mcp.err"

grep -q "started \`elysian serve\`" "$home/mcp.err" || { echo "FAIL: the MCP server did not report starting the API"; cat "$home/mcp.err"; exit 1; }
[ -s "$ELYSIAN_HOME/logs/api.log" ] || { echo "FAIL: the started API wrote no log to $ELYSIAN_HOME/logs/api.log"; exit 1; }
curl -sf "${ELYSIAN_API}/api/status" >/dev/null || { echo "FAIL: the started API stopped with the MCP server; it must outlive the client"; exit 1; }
echo "PASS: with nothing running, the MCP server started the API from the token \`elysian init\` wrote, a memory went in and came back, and the API outlived the client"
