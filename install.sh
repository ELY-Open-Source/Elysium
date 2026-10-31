#!/usr/bin/env bash
# Elysian in one command, on Linux and macOS:
#
#   curl -fsSL https://raw.githubusercontent.com/ELY-Open-Source/Elysian/main/install.sh | bash
#
# It installs uv if it is missing, Elysian with its own Python, the store in ~/.elysian (or
# ELYSIAN_HOME) with an operator token, the checksum-verified MCP server, and registers that
# server with every coding agent it finds. Run from a checkout with --source to install the
# backend and build the MCP server from that checkout instead (needs Go 1.25).
set -euo pipefail

REPO="ELY-Open-Source/Elysian"
METHOD="download"
TAG=""

step() { printf '==> %s\n' "$*"; }
fail() { printf 'elysian install: %s\n' "$*" >&2; exit 1; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --source) METHOD="source"; shift ;;
    --version) TAG="$2"; shift 2 ;;
    *) fail "unknown argument $1; use --source or --version mcp-vX.Y.Z" ;;
  esac
done

command -v curl >/dev/null 2>&1 || fail "curl is required"
SCRIPT_DIR=""
if [[ -n "${BASH_SOURCE[0]:-}" && -f "${BASH_SOURCE[0]}" ]]; then
  SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
fi

platform() {
  local os arch
  case "$(uname -s)" in
    Linux) os="linux" ;;
    Darwin) os="darwin" ;;
    *) fail "unsupported operating system $(uname -s)" ;;
  esac
  case "$(uname -m)" in
    x86_64 | amd64) arch="amd64" ;;
    arm64 | aarch64) arch="arm64" ;;
    *) fail "unsupported architecture $(uname -m)" ;;
  esac
  echo "${os}_${arch}"
}

sha256() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | awk '{print $1}'; else shasum -a 256 "$1" | awk '{print $1}'; fi
}

latest_tag() {
  local body
  body="$(curl -fsSL "https://api.github.com/repos/${REPO}/releases")" || fail "cannot list releases of ${REPO}"
  printf '%s\n' "$body" | grep -oE '"tag_name": *"mcp-[^"]*"' | head -n 1 | sed -E 's/.*"(mcp-[^"]*)".*/\1/'
}

if [[ "$METHOD" == "source" ]]; then
  [[ -n "$SCRIPT_DIR" && -f "$SCRIPT_DIR/backend/pyproject.toml" ]] || fail "--source must run from a checkout"
  command -v go >/dev/null 2>&1 || fail "--source needs Go 1.25 or newer"
else
  [[ -n "$TAG" ]] || TAG="$(latest_tag)"
  [[ -n "$TAG" ]] || fail "no mcp-* release found for ${REPO}"
fi

step "uv"
if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR="$HOME/.local/bin" sh
  export PATH="$HOME/.local/bin:$PATH"
fi
UV="$(command -v uv)"

# The API a previous install started holds the old code and files; stop it before uv replaces them.
# Same rule as the backend's absolute_home: ELYSIAN_HOME with ~ expanded, made absolute, else ~/.elysian.
OLD_HOME="${ELYSIAN_HOME:-$HOME/.elysian}"
case "$OLD_HOME" in "~" | "~/"*) OLD_HOME="$HOME${OLD_HOME#\~}" ;; esac
[[ "$OLD_HOME" == /* ]] || OLD_HOME="$PWD/$OLD_HOME"
pattern="$(printf '%s' "$OLD_HOME/bin/elysian serve" | sed 's/[][\.*^$+?(){}|]/\\&/g')"
pids="$(pgrep -f -- "$pattern")" || [[ $? -eq 1 ]] || fail "pgrep could not list running APIs"
for pid in $pids; do
  kill "$pid"
  for _ in $(seq 50); do kill -0 "$pid" 2>/dev/null || break; sleep 0.2; done
  ! kill -0 "$pid" 2>/dev/null || fail "the running API (pid $pid) did not stop within 10 s; stop it and run again"
  echo "stopped the running API (pid $pid); restart your agents to reconnect"
done

step "Elysian and its Python"
if [[ "$METHOD" == "source" ]]; then
  "$UV" tool install --python 3.12 --reinstall "$SCRIPT_DIR/backend"
else
  "$UV" tool install --python 3.12 --reinstall "elysian @ https://github.com/${REPO}/archive/refs/tags/${TAG}.tar.gz#subdirectory=backend"
fi
ELYSIAN="$("$UV" tool dir --bin)/elysian"
[[ -x "$ELYSIAN" ]] || fail "uv did not install $ELYSIAN"

step "The store and its operator token"
INIT="$("$ELYSIAN" init)"
printf '%s\n' "$INIT"
PYTHON="$("$UV" tool dir)/elysian/bin/python"
HOME_DIR="$(printf '%s' "$INIT" | "$PYTHON" -c 'import json, sys; print(json.load(sys.stdin)["home"])')"
[[ -d "$HOME_DIR" ]] || fail "elysian init named no home"
BIN_DIR="$HOME_DIR/bin"
mkdir -p "$BIN_DIR"
MCP="$BIN_DIR/elysian-mcp"

step "The MCP server"
if [[ "$METHOD" == "source" ]]; then
  (cd "$SCRIPT_DIR/elysian-mcp" && CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o "$MCP" ./cmd/elysian-mcp)
else
  asset="elysian-mcp_$(platform).tar.gz"
  base="https://github.com/${REPO}/releases/download/${TAG}"
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' EXIT
  curl -fsSL "$base/$asset" -o "$tmp/$asset" || fail "cannot download $asset from $TAG"
  curl -fsSL "$base/elysian-mcp_SHA256SUMS.txt" -o "$tmp/SHA256SUMS" || fail "cannot download the checksums of $TAG"
  expected="$(grep -E " \*?${asset}\$" "$tmp/SHA256SUMS" | awk '{print $1}')" || fail "no checksum for $asset in $TAG"
  [[ "$expected" == "$(sha256 "$tmp/$asset")" ]] || fail "checksum mismatch for $asset"
  tar -xzf "$tmp/$asset" -C "$tmp"
  mv "$tmp/elysian-mcp" "$MCP"
  chmod +x "$MCP"
fi
# The MCP server starts the API from the elysian beside it; a client's PATH may not hold uv's bin.
ln -sf "$ELYSIAN" "$BIN_DIR/elysian"

step "Coding agents"
"$MCP" setup

step "Done"
echo "Memory lives in $HOME_DIR. The MCP server is $MCP; it starts the API when an agent first calls it."
echo "Restart your agents to load it. The CLI is $ELYSIAN; run \`$UV tool update-shell\` to put it on PATH."
