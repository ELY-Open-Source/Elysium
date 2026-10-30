param(
  [int]$MaxSteps = 37,
  [int]$Rank = 16,
  [int]$Alpha = 32,
  [int]$MaxLength = 8192,
  [int]$GradientAccumulationSteps = 4,
  [string]$CartridgeId = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$dataset = Join-Path $root ".elysian\training\hme_prd_sft.jsonl"
$adapter = Join-Path $root ".elysian\adapters\hme_core_lora_qwen35_9b"

.\.venv\Scripts\elysian.exe build-prd-training-data `
  --prd-path .\PRD.md `
  --output-path $dataset `
  --max-sections 48

$args = @(
  "train-lora",
  $dataset,
  $adapter,
  "--max-steps", "$MaxSteps",
  "--kind", "hme_core_lora",
  "--rank", "$Rank",
  "--alpha", "$Alpha",
  "--max-length", "$MaxLength",
  "--gradient-accumulation-steps", "$GradientAccumulationSteps"
)

if ($CartridgeId.Length -gt 0) {
  $args += @("--cartridge-id", $CartridgeId)
}

.\.venv\Scripts\elysian.exe @args

Write-Host "Adapter ready: $adapter"
Write-Host "Use with: `$env:ELYSIAN_ADAPTER_DIR='$adapter'"
