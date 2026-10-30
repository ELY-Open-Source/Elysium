#!/usr/bin/env bash
set -euo pipefail

# Elysian MCP installer for Linux and macOS.
#
#   curl -fsSL https://raw.githubusercontent.com/ELY-Open-Source/Elysian/main/elysian-mcp/install.sh | bash
#
# By default it downloads a prebuilt, checksum-verified binary for this platform
# and needs no toolchain. Run with --method source from a repository checkout to
# build with Go instead. The binary is installed into <elysian-home>/bin and
# registered with Codex and Claude Code.

REPO="ELY-Open-Source/Elysian"
CLIENT="both"
SCOPE="project"
SERVER_NAME="elysian"
METHOD="auto"
VERSION=""
PROJECT_ROOT=""
ELYSIAN_HOME="${ELYSIAN_HOME:-}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --client) CLIENT="$2"; shift 2 ;;
    --scope) SCOPE="$2"; shift 2 ;;
    --server-name) SERVER_NAME="$2"; shift 2 ;;
    --method) METHOD="$2"; shift 2 ;;
    --version) VERSION="$2"; shift 2 ;;
    --project-root) PROJECT_ROOT="$2"; shift 2 ;;
    --elysian-home) ELYSIAN_HOME="$2"; shift 2 ;;
    --repo) REPO="$2"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 1 ;;
  esac
done

case "$METHOD" in auto | download | source) ;; *) echo "method must be auto, download, or source" >&2; exit 1 ;; esac

SOURCE="${BASH_SOURCE[0]:-}"
SCRIPT_DIR=""
if [[ -n "$SOURCE" && -f "$SOURCE" ]]; then
  SCRIPT_DIR="$(cd -- "$(dirname -- "$SOURCE")" && pwd)"
fi

if [[ -z "$PROJECT_ROOT" ]]; then
  if [[ -n "$SCRIPT_DIR" && -f "$SCRIPT_DIR/go.mod" ]]; then
    PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
  else
    PROJECT_ROOT="$PWD"
  fi
fi
PROJECT_ROOT="$(cd -- "$PROJECT_ROOT" && pwd)"
[[ -z "$ELYSIAN_HOME" ]] && ELYSIAN_HOME="$HOME/.elysian"
mkdir -p "$ELYSIAN_HOME/bin"
BINARY="$ELYSIAN_HOME/bin/elysian-mcp"

detect_platform() {
  local os arch
  case "$(uname -s)" in
    Linux) os="linux" ;;
    Darwin) os="darwin" ;;
    *) echo "unsupported operating system: $(uname -s)" >&2; exit 1 ;;
  esac
  case "$(uname -m)" in
    x86_64 | amd64) arch="amd64" ;;
    arm64 | aarch64) arch="arm64" ;;
    *) echo "unsupported architecture: $(uname -m)" >&2; exit 1 ;;
  esac
  echo "${os}_${arch}"
}

sha256() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    shasum -a 256 "$1" | awk '{print $1}'
  fi
}

resolve_version() {
  if [[ -n "$VERSION" ]]; then echo "$VERSION"; return 0; fi
  local body
  body="$(curl -fsSL "https://api.github.com/repos/${REPO}/releases" 2>/dev/null)" || return 0
  printf '%s\n' "$body" \
    | grep -oE '"tag_name": *"mcp-[^"]*"' \
    | head -n 1 \
    | sed -E 's/.*"(mcp-[^"]*)".*/\1/' || true
}

build_from_source() {
  command -v go >/dev/null 2>&1 || { echo "Go 1.25 or newer is required to build from source." >&2; exit 1; }
  [[ -n "$SCRIPT_DIR" && -f "$SCRIPT_DIR/go.mod" ]] || { echo "source builds must run from a repository checkout." >&2; exit 1; }
  echo "Building elysian-mcp from source with Go."
  ( cd "$SCRIPT_DIR" && CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o "$BINARY" ./cmd/elysian-mcp )
}

download_binary() {
  local tag="$1" platform asset url sums tmp
  platform="$(detect_platform)"
  asset="elysian-mcp_${platform}.tar.gz"
  url="https://github.com/${REPO}/releases/download/${tag}/${asset}"
  sums="https://github.com/${REPO}/releases/download/${tag}/elysian-mcp_SHA256SUMS.txt"
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' RETURN
  echo "Downloading $asset from release $tag."
  curl -fsSL "$url" -o "$tmp/$asset"
  curl -fsSL "$sums" -o "$tmp/SHA256SUMS"
  local expected actual
  expected="$(grep -E " \*?${asset}\$" "$tmp/SHA256SUMS" | awk '{print $1}' || true)"
  [[ -n "$expected" ]] || { echo "checksum for $asset not found in release." >&2; exit 1; }
  actual="$(sha256 "$tmp/$asset")"
  [[ "$expected" == "$actual" ]] || { echo "checksum mismatch for $asset." >&2; exit 1; }
  tar -xzf "$tmp/$asset" -C "$tmp"
  mv "$tmp/elysian-mcp" "$BINARY"
  chmod +x "$BINARY"
}

acquire() {
  case "$METHOD" in
    source) build_from_source; return ;;
    download)
      local tag; tag="$(resolve_version)"
      [[ -n "$tag" ]] || { echo "no prebuilt release found for ${REPO}." >&2; exit 1; }
      download_binary "$tag"; return ;;
    auto)
      local tag; tag="$(resolve_version)"
      if [[ -n "$tag" ]]; then
        download_binary "$tag"
      else
        echo "No prebuilt release available; building from source."
        build_from_source
      fi ;;
  esac
}

acquire

"$BINARY" setup \
  --client "$CLIENT" \
  --scope "$SCOPE" \
  --server-name "$SERVER_NAME" \
  --project-root "$PROJECT_ROOT" \
  --elysian-home "$ELYSIAN_HOME" \
  --binary "$BINARY"
