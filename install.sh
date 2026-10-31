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
running_apis() {
  local needle="$1/bin/elysian serve" dir command
  if [[ -d /proc/self ]]; then
    for dir in /proc/[0-9]*; do
      command="$(tr '\0' ' ' < "$dir/cmdline" 2>/dev/null)" || continue
      [[ "$command" == *"$needle"* ]] && echo "${dir#/proc/}"
    done
    return 0
  fi
  pgrep -f -- "$(printf '%s' "$needle" | sed 's/[][\.*^$+?(){}|]/\\&/g')" || [[ $? -eq 1 ]] || fail "pgrep could not list running APIs"
}
# Same rule as the backend's absolute_home: ELYSIAN_HOME with ~ expanded, made absolute, else ~/.elysian.
OLD_HOME="${ELYSIAN_HOME:-$HOME/.elysian}"
case "$OLD_HOME" in "~" | "~/"*) OLD_HOME="$HOME${OLD_HOME#\~}" ;; esac
[[ "$OLD_HOME" == /* ]] || OLD_HOME="$PWD/$OLD_HOME"
# The sign-in service would restart the API stopped below; stop the service first.
LABEL="com.elysian.api"
if [[ "$(uname -s)" == "Darwin" ]]; then
  if launchctl print "gui/$(id -u)/$LABEL" >/dev/null 2>&1; then launchctl bootout "gui/$(id -u)/$LABEL"; fi
elif command -v systemctl >/dev/null 2>&1 && systemctl --user cat elysian.service >/dev/null 2>&1; then
  systemctl --user stop elysian.service
fi
pids=""
# The MCP server starts the API from its own resolved directory, so match the real path; no home, no API.
if [[ -d "$OLD_HOME/bin" ]]; then
  pids="$(running_apis "$(cd -- "$OLD_HOME" && pwd -P)")"
fi
for pid in $pids; do
  kill "$pid"
  for _ in $(seq 50); do kill -0 "$pid" 2>/dev/null || break; sleep 0.2; done
  ! kill -0 "$pid" 2>/dev/null || fail "the running API (pid $pid) did not stop within 10 s; stop it and run again"
  echo "stopped the running API (pid $pid); restart your agents to reconnect"
done

step "Elysian and its Python"
# rapidocr pulls the GUI build of OpenCV, which needs X libraries; the headless build Elysian lists serves the same cv2.
EXCLUDES="$(mktemp)"
echo "opencv-python" > "$EXCLUDES"
if [[ "$METHOD" == "source" ]]; then
  "$UV" tool install --python 3.12 --reinstall --excludes "$EXCLUDES" "$SCRIPT_DIR/backend"
else
  "$UV" tool install --python 3.12 --reinstall --excludes "$EXCLUDES" "elysian @ https://github.com/${REPO}/archive/refs/tags/${TAG}.tar.gz#subdirectory=backend"
fi
rm -f "$EXCLUDES"
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

step "Start at sign-in"
xml() { printf '%s' "$1" | sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g'; }
if [[ "$(uname -s)" == "Darwin" ]]; then
  mkdir -p "$HOME/Library/LaunchAgents" "$HOME_DIR/logs"
  SERVICE="$HOME/Library/LaunchAgents/$LABEL.plist"
  cat > "$SERVICE" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array><string>$(xml "$BIN_DIR/elysian")</string><string>serve</string></array>
  <key>EnvironmentVariables</key><dict><key>ELYSIAN_HOME</key><string>$(xml "$HOME_DIR")</string></dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>
  <key>StandardOutPath</key><string>$(xml "$HOME_DIR/logs/api.log")</string>
  <key>StandardErrorPath</key><string>$(xml "$HOME_DIR/logs/api.log")</string>
</dict></plist>
EOF
  launchctl bootstrap "gui/$(id -u)" "$SERVICE"
elif command -v systemctl >/dev/null 2>&1 && systemctl --user show-environment >/dev/null 2>&1; then
  SERVICE="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/elysian.service"
  mkdir -p "$(dirname -- "$SERVICE")"
  # systemd refuses a program path holding a quote, backslash or control character; % is a specifier.
  [[ "$BIN_DIR" != *[\"\'\\[:cntrl:]]* ]] || fail "systemd cannot run a program from $BIN_DIR: the path holds a quote, backslash or control character; set ELYSIAN_HOME to a plainer path"
  UNIT_HOME="${HOME_DIR//%/%%}"
  UNIT_EXEC="${BIN_DIR//%/%%}/elysian"
  cat > "$SERVICE" <<EOF
[Unit]
Description=Elysian local memory API

[Service]
Environment="ELYSIAN_HOME=$UNIT_HOME"
ExecStart="$UNIT_EXEC" serve
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
EOF
  systemctl --user daemon-reload
  systemctl --user enable --now elysian.service
else
  SERVICE=""
  echo "no systemd user session here, so nothing starts at sign-in; the MCP server starts the API when an agent first calls it"
fi
if [[ -n "$SERVICE" ]]; then
  # Another store's API on the port would answer too; only this home counts.
  served() { curl -fsS --max-time 2 http://127.0.0.1:8765/api/status | "$PYTHON" -c 'import json, os, sys; home = json.load(sys.stdin)["data_home"]; print(os.path.realpath(home) if os.path.isabs(home) else "relative " + home)'; }
  WANT="$(cd -- "$HOME_DIR" && pwd -P)"
  GOT=""
  DEADLINE=$((SECONDS + 90))
  while ((SECONDS < DEADLINE)); do
    GOT="$(served 2>/dev/null || true)"
    [[ "$GOT" == "$WANT" ]] && break
    # An older API names its home relative to a directory this script cannot know.
    [[ "$GOT" != "relative "* ]] || fail "the API at 127.0.0.1:8765 reports the relative home ${GOT#relative }, so its store cannot be told from here; stop it and run again"
    sleep 1
  done
  [[ "$GOT" == "$WANT" ]] || fail "the sign-in service $SERVICE did not serve $WANT at 127.0.0.1:8765 within 90 s (it answered: ${GOT:-nothing}); see $HOME_DIR/logs/api.log or journalctl --user -u elysian"
  echo "the API runs from $SERVICE and starts at every sign-in"
fi

step "Coding agents"
"$MCP" setup

step "Done"
echo "Memory lives in $HOME_DIR. The MCP server is $MCP; it starts the API itself whenever the API is down."
echo "Any other MCP client: paste the any_other_client entry printed above into its MCP config."
echo "Each agent above now recalls and saves memory by itself through its hooks; Claude Code, Droid, Gemini, Grok and Kiro run them once you trust a folder."
echo "Restart your agents to load it. The CLI is $ELYSIAN; run \`$UV tool update-shell\` to put it on PATH."
