#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

max_steps="${MAX_STEPS:-37}"
rank="${RANK:-16}"
alpha="${ALPHA:-32}"
max_length="${MAX_LENGTH:-8192}"
gradient_accumulation_steps="${GRADIENT_ACCUMULATION_STEPS:-4}"
cartridge_id="${CARTRIDGE_ID:-}"

dataset=.elysium/training/hme_prd_sft.jsonl
adapter=.elysium/adapters/hme_core_lora_qwen35_9b

.venv/bin/elysium build-prd-training-data \
  --prd-path ./PRD.md \
  --output-path "$dataset" \
  --max-sections 48

args=(train-lora "$dataset" "$adapter"
  --max-steps "$max_steps"
  --kind hme_core_lora
  --rank "$rank"
  --alpha "$alpha"
  --max-length "$max_length"
  --gradient-accumulation-steps "$gradient_accumulation_steps")

if [ -n "$cartridge_id" ]; then
  args+=(--cartridge-id "$cartridge_id")
fi

.venv/bin/elysium "${args[@]}"

echo "Adapter ready: $adapter"
echo "Use with: ELYSIUM_ADAPTER_DIR=$adapter"
