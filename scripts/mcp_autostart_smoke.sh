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

python3 - "$home/elysian-mcp" "$home/mcp.err" <<'PY'
import json
import subprocess
import sys

with open(sys.argv[2], "w", encoding="utf-8") as errors:
    proc = subprocess.Popen([sys.argv[1], "server"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errors, text=True)


def call(id_, method, params):
    proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": id_, "method": method, "params": params}) + "\n")
    proc.stdin.flush()
    while True:
        line = proc.stdout.readline()
        if not line:
            raise SystemExit(f"FAIL: the MCP server closed the pipe at {method}; its stderr:\n" + open(sys.argv[2]).read())
        answer = json.loads(line)
        if answer.get("id") == id_:
            if "error" in answer:
                raise SystemExit(f"FAIL: {method} returned {answer['error']}")
            return answer["result"]


def tool(id_, name, arguments):
    result = call(id_, "tools/call", {"name": name, "arguments": arguments})
    if result.get("isError"):
        raise SystemExit(f"FAIL: {name} returned an error: {result['content']}")
    return result["structuredContent"]


call(1, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "autostart-smoke", "version": "0"}})
proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
proc.stdin.flush()
atom = tool(2, "remember", {"text": "the spare key hangs behind the calendar", "scenario": "home"})["atom"]
hits = tool(3, "search_atoms", {"query": "spare key calendar"})["hits"]
if not hits or hits[0]["atom"]["atom_id"] != atom["atom_id"]:
    raise SystemExit(f"FAIL: the memory written through MCP is not found: {hits}")
proc.stdin.close()
proc.wait(timeout=10)
PY

grep -q "started \`elysian serve\`" "$home/mcp.err" || { echo "FAIL: the MCP server did not report starting the API"; cat "$home/mcp.err"; exit 1; }
[ -s "$ELYSIAN_HOME/logs/api.log" ] || { echo "FAIL: the started API wrote no log to $ELYSIAN_HOME/logs/api.log"; exit 1; }
curl -sf "${ELYSIAN_API}/api/status" >/dev/null || { echo "FAIL: the started API stopped with the MCP server; it must outlive the client"; exit 1; }
echo "PASS: with nothing running, the MCP server started the API from the token \`elysian init\` wrote, a memory went in and came back, and the API outlived the client"
