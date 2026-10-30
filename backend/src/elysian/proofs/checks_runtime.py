"""Runtime adapter binding, gold-adapter generation, launch profiles, and the removed module check.

Moved out of suite.py so the suite order stays readable; each method is a check the
suite runs, and the suite class mixes these in.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .. import adapters
from ..compiler import ContextCompiler
from ..config import Settings
from ..db import Database
from ..evaluation_schemas import (
    ProofCheck,
)
from ..evidence_graph import EvidenceGraphService
from ..profiles import runtime_profile_report
from ..runtime import QwenRuntime
from ..runtime_schemas import AdapterState
from ..schemas import (
    RuntimeProfile,
    TrainingAdapterKind,
)
from ..verifier import Verifier

# A fixed puzzle count per hop depth. The old suite re-rolled until the running rate crossed its
from .checks_common import (
    GOLD_ADAPTERS,
    _deferred_without_model,
)
from .report import (
    compact_generation_context,
    write_json,
)
from .training_trace import (
    count_safetensor_keys,
    peft_config_loads,
)


def _generation_adapter(
    settings: Settings,
    database: Database,
    kind: TrainingAdapterKind = TrainingAdapterKind.hme_core_lora,
) -> tuple[adapters.AdapterSource | None, AdapterState, str]:
    """Resolve the way generation does, mounted cartridges included, so proof and generation name one copy."""
    sources, _mounted = adapters.discover(settings, database)
    return adapters.resolve(sources, settings, kind)


class RuntimeChecks:
    """Runtime adapter binding, gold-adapter generation, launch profiles, and the removed module check."""

    settings: Settings
    db: Database

    def _runtime_adapter_check(self, proof_root: Path) -> ProofCheck:
        artifact = proof_root / "runtime_adapter.json"
        deferred = _deferred_without_model(
            self.settings,
            artifact,
            "Runtime Adapter Binding",
            "PRD 18 requires the local model package to run with the trained adapter, and PRD 12.1 requires HME-Core-LoRA to be usable by the Qwen runtime.",
            "elysian runtime-generation-proof with ELYSIAN_MODEL_DIR set",
        )
        if deferred is not None:
            return deferred
        runtime = QwenRuntime(self.settings)
        status = runtime.status()
        adapter, _adapter_state, _adapter_reason = _generation_adapter(self.settings, self.db)
        weight_path = adapter.path / "adapter_model.safetensors" if adapter else None
        payload = {
            "runtime_status": status.model_dump(mode="json"),
            "resolved_adapter": {
                "path": str(adapter.path) if adapter else None,
                "kind": adapter.manifest.kind.value if adapter else None,
                "adapter_id": adapter.manifest.adapter_id if adapter else None,
                "sha256": adapter.manifest.sha256 if adapter else None,
                "base_model": adapter.manifest.base_model if adapter else None,
                "weight_path": str(weight_path) if weight_path else None,
                "safetensor_keys": count_safetensor_keys(weight_path) if weight_path else 0,
                "peft_config_ok": peft_config_loads(adapter.path) if adapter else False,
            },
        }
        artifact = proof_root / "runtime_adapter.json"
        write_json(artifact, payload)
        valid = (
            status.available
            and adapter is not None
            and adapter.manifest.kind == TrainingAdapterKind.hme_core_lora
            and adapter.manifest.base_model == self.settings.model_id
            and status.adapter_path == str(adapter.path)
            and weight_path is not None
            and count_safetensor_keys(weight_path) > 0
            and peft_config_loads(adapter.path)
        )
        return ProofCheck(
            name="Runtime Adapter Binding",
            requirement="PRD 18 requires the local model package to run with the trained adapter, and PRD 12.1 requires HME-Core-LoRA to be usable by the Qwen runtime.",
            status="passed" if valid else "failed",
            evidence=[str(artifact)],
            detail=(
                f"{status.backend} runtime resolves {adapter.manifest.kind.value} at {adapter.path}"
                if adapter
                else "runtime adapter resolution is empty"
            ),
        )

    def _runtime_generation_check(self, proof_root: Path) -> ProofCheck:
        artifact = proof_root / "runtime_generation.json"
        deferred = _deferred_without_model(
            self.settings,
            artifact,
            "Runtime Adapter Generation",
            "PRD 12.1 and PRD 18 require the trained HME-Core-LoRA adapter to be loaded by the local Qwen runtime and used for an evidence-cited generation.",
            "elysian proof-suite --cartridge-id <id> with ELYSIAN_MODEL_DIR set",
        )
        if deferred is not None:
            return deferred
        retrieval_question = (
            "Using the Elysian PRD evidence, state the PRD 12.1 local training adapter "
            "requirements for HME-Core-LoRA, HME-Vision-LoRA, HME-TTT-VL, "
            "HME-Visual-MTP, HME-Router, and HME-Retrieval. Return JSON with atom id "
            "citations."
        )
        proof_settings = self.settings.model_copy(update={"max_new_tokens": 256, "temperature": 0.0})
        runtime = QwenRuntime(proof_settings)
        payload: dict[str, Any] = {
            "question": retrieval_question,
            "status": "failed",
        }
        try:
            compiler = ContextCompiler(proof_settings, self.db)
            context = compiler.compile(retrieval_question, RuntimeProfile.library_100m)
            context = compact_generation_context(context, "12.1")
            if not context.hits:
                raise RuntimeError("No PRD text evidence was available for runtime generation proof.")
            generation_question = (
                "According to the retrieved PRD evidence, which local training adapters does "
                "PRD 12.1 require? Answer with one compact JSON object: a \"citations\" field "
                "naming the atom ids you actually used, and a \"sentence\" field listing them."
            )
            payload["generation_question"] = generation_question
            status = runtime.status()
            adapter, _adapter_state, _adapter_reason = _generation_adapter(proof_settings, self.db)
            generation = runtime.generate(generation_question, context)
            answer, citations, citation_report = Verifier().verify_answer(generation.text, context)
            claim_id = EvidenceGraphService(proof_settings, self.db).record_answer(
                generation_question,
                answer,
                citation_report,
                context,
            )
            payload.update(
                {
                    "status": "passed",
                    "runtime_status": status.model_dump(mode="json"),
                    "adapter": {
                        "path": generation.adapter_path,
                        "kind": generation.adapter_kind,
                        "adapter_id": generation.adapter_id,
                        "sha256": generation.adapter_sha256,
                    },
                    "tokens": {
                        "input": generation.input_tokens,
                        "output": generation.output_tokens,
                    },
                    "context": {
                        "profile": context.plan.profile.value,
                        "hit_ids": [hit.atom.atom_id for hit in context.hits],
                        "token_equivalent": context.token_equivalent,
                        "cache_trace_id": context.cache_trace_id,
                    },
                    "raw_generation": generation.text,
                    "verified_answer": answer,
                    "citations": citations,
                    "evidence_graph_claim_id": claim_id,
                    "verifier": citation_report.model_dump(mode="json"),
                }
            )
            named = [name for name in GOLD_ADAPTERS if name in answer]
            cited_atoms = [
                hit.atom for hit in context.hits if hit.atom.atom_id in set(citations)
            ]
            supported = [atom for atom in cited_atoms if sum(name in (atom.text or "") for name in GOLD_ADAPTERS) >= 3]
            valid = (
                status.available
                and generation.backend == "transformers"
                and adapter is not None
                and generation.adapter_path == str(adapter.path)
                and generation.adapter_kind == TrainingAdapterKind.hme_core_lora.value
                and generation.adapter_sha256 == adapter.manifest.sha256
                and bool(context.hits)
                and bool(generation.text.strip())
                and (generation.output_tokens or 0) > 0
                and len(named) >= 5
                and bool(citations)
                and citation_report.citation_accuracy == 1.0
                and bool(supported)
            )
            payload["answer_adapters"] = named
            payload["cited_atoms"] = [atom.atom_id for atom in cited_atoms]
            payload["supporting_citations"] = [atom.atom_id for atom in supported]
            if not valid:
                payload["status"] = "failed"
            write_json(artifact, payload)
            return ProofCheck(
                name="Runtime Adapter Generation",
                requirement="PRD 12.1 and PRD 18 require the trained HME-Core-LoRA adapter to be loaded by the local Qwen runtime and used for an evidence-cited generation.",
                status="passed" if valid else "failed",
                evidence=[str(artifact)],
                detail=(
                    f"{generation.backend} generated {generation.output_tokens} tokens with "
                    f"{generation.adapter_kind} citation accuracy "
                    f"{citation_report.citation_accuracy:.2f}"
                ),
            )
        except Exception as exc:  # noqa: BLE001  # a probe records its failure instead of crashing the proof run
            payload["error"] = str(exc)
            write_json(artifact, payload)
            return ProofCheck(
                name="Runtime Adapter Generation",
                requirement="PRD 12.1 and PRD 18 require the trained HME-Core-LoRA adapter to be loaded by the local Qwen runtime and used for an evidence-cited generation.",
                status="failed",
                evidence=[str(artifact)],
                detail=f"runtime generation failed: {exc}",
            )
        finally:
            runtime.unload()

    def _runtime_profile_check(self, proof_root: Path) -> ProofCheck:
        report = runtime_profile_report(self.settings)
        artifact = proof_root / "runtime_profiles.json"
        artifact.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        required_runtimes = {"SGLang", "vLLM", "KTransformers", "llama.cpp"}
        runtimes = {profile.runtime for profile in report.profiles}
        gaps = [f"{item.name}: {item.detail}" for item in report.validations if item.status == "missing"]
        unregistered = sorted(required_runtimes - runtimes)
        if unregistered:
            gaps.append("no profile registered for: " + ", ".join(unregistered))
        if not gaps and report.status != "ready":
            gaps.append(f"the profile report says {report.status}")
        valid = not gaps
        return ProofCheck(
            name="Runtime Profile Delivery",
            requirement="PRD 13.1 requires SGLang as the main runtime plus vLLM, KTransformers, and llama.cpp deployment profiles.",
            status="passed" if valid else "failed",
            evidence=[str(artifact)],
            detail="registered runtimes: " + ", ".join(profile.name for profile in report.profiles),
            reason="; ".join(gaps),
            rerun="install the launcher in the environment the profile probes (the probe command is in runtime_profiles.json), then elysian runtime-profiles",
        )

    def _research_module_check(self, proof_root: Path) -> ProofCheck:
        """The old version of this check could not fail, so it proved nothing.

        It compiled a query, asked the research-module service for eight module reports, and
        passed when every list was non-empty. The module vectors it ranks with are SHA256-derived
        placeholders, so a non-empty list is a property of the loop, not of the system.
        """
        artifact = proof_root / "research_modules.json"
        write_json(
            artifact,
            {
                "claim": "PRD 11 research modules",
                "verdict": "removed",
                "why": "the check asserted non-empty lists built from SHA256-derived placeholder vectors",
            },
        )
        return ProofCheck(
            name="Research Module Delivery",
            requirement="PRD 11 requires V-NSA, DVKV, X-Modal KV Sharing, Speculative Context Prefetch, Predictive KV Eviction, Learned Evidence Graph, Differentiable Retrieval Adapter, and Sleep-Time Visual Consolidation.",
            status="removed",
            evidence=[str(artifact)],
            detail="no measurable claim exists per module; the previous check passed on non-empty lists",
            reason="the check could not fail: eight named modules produced non-empty lists by construction",
            rerun="write one measurable claim per module, then re-add the check",
        )

