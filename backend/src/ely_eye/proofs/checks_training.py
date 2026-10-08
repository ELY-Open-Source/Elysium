"""Adapter training and the learned-memory adapters bound into a cartridge.

Moved out of suite.py so the suite order stays readable; each method is a check the
suite runs, and the suite class mixes these in.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..config import Settings
from ..db import Database
from ..evaluation_schemas import (
    ProofCheck,
)
from ..schemas import (
    AdapterManifest,
    TrainingAdapterKind,
)
from ..training_common import sha256_file, sha256_tree
from ..training_metrics import safetensor_weight_stats

# A fixed puzzle count per hop depth. The old suite re-rolled until the running rate crossed its
from .report import (
    read_json_or_empty,
    write_json,
)
from .training_trace import (
    count_safetensor_keys,
    peft_config_loads,
    validate_training_contract,
    validate_training_proof,
    validate_training_trace,
)


class TrainingChecks:
    """Adapter training and the learned-memory adapters bound into a cartridge."""

    settings: Settings
    db: Database
    required_adapters: tuple[TrainingAdapterKind, ...]

    def _adapter_training_check(self, cartridge_id: str, cartridge_root: Path, proof_root: Path) -> ProofCheck:
        rows: list[dict[str, Any]] = []
        missing: list[str] = []
        manifests = self._adapter_manifests(cartridge_id)
        for kind in self.required_adapters:
            item = manifests.get(kind)
            if item is None:
                missing.append(f"{kind.value}: no adapter manifest")
                continue
            manifest, adapter_root = item
            weight_path = adapter_root / "adapter_model.safetensors"
            dataset_path = Path(manifest.dataset_path)
            cartridge_adapter = cartridge_root / "adapters" / kind.value / "adapter_manifest.json"
            weight_report = safetensor_weight_stats(weight_path)
            keys = int(weight_report["tensor_count"])
            summary = read_json_or_empty(adapter_root / "training_summary.json")
            summary_weight_sha = summary.get("adapter_weight_sha256")
            summary_weight_sha_ok = (
                isinstance(summary_weight_sha, str) and summary_weight_sha == weight_report["sha256"]
            )
            manifest_weight_sha_ok = (
                isinstance(manifest.adapter_weight_sha256, str)
                and manifest.adapter_weight_sha256 == weight_report["sha256"]
            )
            manifest_weight_stats_ok = (
                manifest.adapter_tensor_count == weight_report["tensor_count"]
                and manifest.adapter_lora_tensor_count == weight_report["lora_tensor_count"]
                and manifest.adapter_total_elements == weight_report["total_elements"]
                and manifest.adapter_nonzero_elements == weight_report["nonzero_elements"]
                and manifest.adapter_nonzero_elements > 0
                and manifest.adapter_lora_tensor_count > 0
                and manifest.adapter_weights_finite
            )
            peft_ok = peft_config_loads(adapter_root)
            dataset_sha_ok = dataset_path.exists() and sha256_file(dataset_path) == manifest.dataset_sha256
            tree_sha_ok = sha256_tree(adapter_root) == manifest.sha256
            cartridge_bound = cartridge_adapter.exists()
            trace_report = validate_training_trace(manifest, adapter_root)
            proof_report = validate_training_proof(manifest, adapter_root)
            contract_report = validate_training_contract(manifest)
            # Named conditions, so a failure says which promise broke instead of listing the adapters that happened to be present.
            conditions: list[tuple[str, bool]] = [
                ("sample_count", manifest.sample_count > 0),
                ("max_steps", manifest.max_steps > 0),
                ("trainable_params", manifest.trainable_params > 0),
                ("final_loss recorded", manifest.final_loss is not None),
                ("safetensors readable", weight_report["valid"]),
                ("weight sha256 matches the training summary", summary_weight_sha_ok),
                ("weight sha256 matches the manifest", manifest_weight_sha_ok),
                ("weight statistics match the manifest", manifest_weight_stats_ok),
                ("peft config loads", peft_ok),
                ("dataset sha256 matches", dataset_sha_ok),
                ("adapter tree sha256 matches", tree_sha_ok),
                ("adapter is bound into the cartridge", cartridge_bound),
                ("training trace verifies", trace_report["valid"]),
                ("training proof verifies", proof_report["valid"]),
                ("training contract verifies", contract_report["valid"]),
            ]
            valid = all(ok for _, ok in conditions)
            if not valid:
                gaps = ", ".join(name for name, ok in conditions if not ok)
                missing.append(f"{kind.value}: {gaps}")
            rows.append(
                {
                    "kind": kind.value,
                    "adapter": str(adapter_root),
                    "dataset": str(dataset_path),
                    "sample_count": manifest.sample_count,
                    "max_steps": manifest.max_steps,
                    "trainable_params": manifest.trainable_params,
                    "final_loss": manifest.final_loss,
                    "safetensor_keys": keys,
                    "adapter_weight_sha256": weight_report["sha256"],
                    "adapter_weight_sha256_ok": summary_weight_sha_ok and manifest_weight_sha_ok,
                    "adapter_weight_stats_ok": manifest_weight_stats_ok,
                    "adapter_weight_stats": weight_report,
                    "dataset_sha256_ok": dataset_sha_ok,
                    "adapter_sha256_ok": tree_sha_ok,
                    "peft_config_ok": peft_ok,
                    "cartridge_bound": cartridge_bound,
                    "training_contract": contract_report,
                    "training_trace": trace_report,
                    "training_proof": proof_report,
                }
            )
        artifact = proof_root / "adapter_training.json"
        write_json(artifact, {"adapters": rows})
        return ProofCheck(
            name="Adapter Training Proof",
            requirement="PRD 12.1 requires HME-Core-LoRA, HME-Vision-LoRA, HME-TTT-VL, HME-Visual-MTP, HME-Router, and HME-Retrieval trained adapters.",
            status="failed" if missing else "passed",
            evidence=[str(artifact), str(self.settings.adapters_dir), str(cartridge_root / "adapters")],
            detail="adapters with verified training evidence: " + ", ".join(row["kind"] for row in rows),
            reason="; ".join(missing),
            rerun="train the missing adapters (ely-eye train-lora) or attach them (ely-eye attach-adapter), then ely-eye proof-suite --cartridge-id <id>",
        )

    def _learned_memory_recall_check(
        self,
        cartridge_id: str,
        cartridge_root: Path,
        proof_root: Path,
    ) -> ProofCheck:
        manifests = self._adapter_manifests(cartridge_id)
        learned_kinds = (
            TrainingAdapterKind.hme_ttt_vl,
            TrainingAdapterKind.hme_core_lora,
            TrainingAdapterKind.hme_retrieval,
        )
        rows: list[dict[str, Any]] = []
        missing: list[str] = []
        for kind in learned_kinds:
            item = manifests.get(kind)
            if item is None:
                missing.append(f"{kind.value}: no adapter manifest")
                continue
            manifest, adapter_root = item
            weight_path = adapter_root / "adapter_model.safetensors"
            cartridge_weight = cartridge_root / "adapters" / kind.value / "adapter_model.safetensors"
            rows.append(
                {
                    "kind": kind.value,
                    "adapter": str(adapter_root),
                    "cartridge_weight": str(cartridge_weight),
                    "base_model": manifest.base_model,
                    "dataset_sha256": manifest.dataset_sha256,
                    "sample_count": manifest.sample_count,
                    "trainable_params": manifest.trainable_params,
                    "safetensor_keys": count_safetensor_keys(weight_path),
                    "cartridge_weight_present": cartridge_weight.exists(),
                    "peft_config_ok": peft_config_loads(adapter_root),
                }
            )
            if not cartridge_weight.exists():
                missing.append(f"{kind.value}: the cartridge holds no adapter weights")
            elif count_safetensor_keys(weight_path) <= 0:
                missing.append(f"{kind.value}: the adapter weight file holds no tensors")
        artifact = proof_root / "learned_memory_recall.json"
        write_json(
            artifact,
            {
                "cartridge_id": cartridge_id,
                "learned_memory_adapters": rows,
                "runtime_binding": "Adapters are stored inside the Context Cartridge and can be loaded without source files.",
            },
        )
        return ProofCheck(
            name="Learned Memory Recall",
            requirement="PRD 14.2 and 15.4 require TTT-VL and LoRA capsule memory to be stored as cartridge-loadable adapter weights.",
            status="failed" if missing else "deferred",
            evidence=[str(artifact), str(cartridge_root / "adapters" / TrainingAdapterKind.hme_ttt_vl.value)],
            detail=(
                "weights load for " + ", ".join(row["kind"] for row in rows)
                + "; no recall number was measured"
            ),
            reason=(
                "the check loads adapter weights and never asks the model to remember anything, so it "
                "cannot carry the word recall; the load evidence is real, the recall claim is not yet measured"
            ),
            rerun="add a recall probe that answers questions with and without the adapter, then ely-eye proof-suite --cartridge-id <id>",
        )

    def _adapter_manifests(
        self,
        cartridge_id: str,
    ) -> dict[TrainingAdapterKind, tuple[AdapterManifest, Path]]:
        candidates: dict[TrainingAdapterKind, list[tuple[AdapterManifest, Path]]] = {}
        for path in sorted(self.settings.adapters_dir.glob("*/adapter_manifest.json")):
            manifest = AdapterManifest.model_validate_json(path.read_text(encoding="utf-8"))
            candidates.setdefault(manifest.kind, []).append((manifest, path.parent))
        selected: dict[TrainingAdapterKind, tuple[AdapterManifest, Path]] = {}
        for kind, items in candidates.items():
            items.sort(
                key=lambda item: (
                    item[0].cartridge_id == cartridge_id,
                    (item[1] / "adapter_model.safetensors").stat().st_mtime
                    if (item[1] / "adapter_model.safetensors").exists()
                    else 0.0,
                ),
                reverse=True,
            )
            selected[kind] = items[0]
        return selected

