#!/usr/bin/env bash
# The one-command install on a machine with no Python and no Git: a bare Debian container.
#
#   bash scripts/install_acceptance.sh            # the published command, against the newest release
#   bash scripts/install_acceptance.sh --source   # this checkout (Go is fetched inside the container)
#
# After the install it drives the installed MCP server over stdio, as a client would, with the
# Python uv installed for Elysian: one memory in, the same memory back.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mode="${1:-release}"
case "$mode" in release | --source) ;; *) echo "usage: $0 [--source]" >&2; exit 2 ;; esac
GO_VERSION="1.25.4"

docker run --rm -i -v "$root:/src:ro" -e MODE="$mode" -e GO_VERSION="$GO_VERSION" debian:bookworm-slim bash -euo pipefail <<'IN'
apt-get update -qq >/dev/null
apt-get install -y -qq curl ca-certificates >/dev/null
if command -v python3 >/dev/null || command -v python >/dev/null || command -v git >/dev/null; then
  echo "FAIL: the container is supposed to have no Python and no Git"; exit 1
fi
cd /root
if [ "$MODE" = "--source" ]; then
  arch="$(dpkg --print-architecture)"
  curl -fsSL "https://go.dev/dl/go${GO_VERSION}.linux-${arch}.tar.gz" | tar -xz -C /usr/local
  export PATH="/usr/local/go/bin:$PATH"
  mkdir /work
  cp -r /src/install.sh /src/backend /src/elysian-mcp /work/
  bash /work/install.sh --source
else
  curl -fsSL https://raw.githubusercontent.com/ELY-Open-Source/Elysian/main/install.sh | bash
fi
python="$("$HOME/.local/bin/uv" tool dir)/elysian/bin/python"
"$python" /src/scripts/mcp_roundtrip.py "$HOME/.elysian/bin/elysian-mcp" /tmp/mcp.err
grep -q "started \`elysian serve\`" /tmp/mcp.err || { echo "FAIL: the MCP server did not start the API"; cat /tmp/mcp.err; exit 1; }
echo "PASS: a bare Debian container installed Elysian with one command and a client wrote and read a memory"
IN
