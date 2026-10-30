$ErrorActionPreference = "Stop"

Set-Location (Split-Path -Parent $PSScriptRoot)
$distro = if ($env:ELYSIAN_WSL_DISTRO) { $env:ELYSIAN_WSL_DISTRO } else { "Ubuntu" }

if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
  throw "WSL is required for the vLLM Linux runtime."
}

$wslRoot = (wsl.exe -d $distro wslpath -a (Get-Location).Path).Trim()
$command = @"
set -euo pipefail
cd "$wslRoot"
source .venv-linux-vllm/bin/activate
export VLLM_USE_FLASHINFER_SAMPLER=0
python -m vllm.entrypoints.openai.api_server \
  --model "`${ELYSIAN_MODEL_DIR:-Qwen/Qwen3.5-9B}" \
  --served-model-name Qwen/Qwen3.5-9B \
  --host 127.0.0.1 \
  --port 8001 \
  --max-model-len 16384 \
  --quantization fp8 \
  --enable-prefix-caching \
  --gpu-memory-utilization 0.90 \
  --reasoning-parser qwen3
"@

wsl.exe -d $distro -- bash -lc $command
