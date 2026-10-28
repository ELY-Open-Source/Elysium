$ErrorActionPreference = "Stop"

Set-Location (Split-Path -Parent $PSScriptRoot)
$distro = if ($env:ELYSIUM_WSL_DISTRO) { $env:ELYSIUM_WSL_DISTRO } else { "Ubuntu" }

if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
  throw "WSL is required for the KTransformers Linux runtime."
}

$wslRoot = (wsl.exe -d $distro wslpath -a (Get-Location).Path).Trim()
$command = @"
set -euo pipefail
cd "$wslRoot"
source .venv-linux/bin/activate
export SGLANG_ALLOW_OVERWRITE_LONGER_CONTEXT_LEN=1
python -m sglang.launch_server \
  --model-path Qwen/Qwen3.5-9B \
  --port 8002 \
  --context-length 1010000 \
  --kt-cpuinfer 16 \
  --cpu-offload-gb 48
"@

wsl.exe -d $distro -- bash -lc $command
