"""The proof suite: one check per claim, and a verdict that says what it proves.
"""

from __future__ import annotations

import hashlib
import secrets
from pathlib import Path
from typing import Literal

from ..cartridge import CartridgeService
from ..config import Settings, get_settings
from ..db import Database
from ..evaluation_schemas import (
    ProofCheck,
    ProofSuiteReport,
)
from ..schemas import (
    CartridgeManifest,
    TrainingAdapterKind,
)
from .checks_cartridge import CartridgeChecks
from .checks_runtime import RuntimeChecks
from .checks_training import TrainingChecks
from .checks_visual import VisualChecks
from .report import (
    relative_artifacts,
)


class PRDProofSuite(TrainingChecks, CartridgeChecks, RuntimeChecks, VisualChecks):
    required_adapters = (
        TrainingAdapterKind.hme_core_lora,
        TrainingAdapterKind.hme_vision_lora,
        TrainingAdapterKind.hme_ttt_vl,
        TrainingAdapterKind.hme_visual_mtp,
        TrainingAdapterKind.hme_router,
        TrainingAdapterKind.hme_retrieval,
    )

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.db = Database(self.settings)
        self.cartridges = CartridgeService(self.settings, self.db)

    def run(self, cartridge_id: str | None = None) -> ProofSuiteReport:
        row = self._resolve_cartridge(cartridge_id)
        cartridge_id = str(row["cartridge_id"])
        root = Path(row["root_path"])
        manifest = CartridgeManifest.model_validate_json(row["manifest_json"])
        proof_id = self._proof_id(cartridge_id, manifest.dna)
        proof_root = self.settings.data_dir / "eval_proofs" / proof_id
        proof_root.mkdir(parents=True, exist_ok=True)
        dna_before = manifest.dna

        asset_check, manifest = self._cartridge_assets_check(cartridge_id, root, proof_root)
        checks = [
            self._adapter_training_check(cartridge_id, root, proof_root),
            self._runtime_adapter_check(proof_root),
            self._runtime_generation_check(proof_root),
            asset_check,
            self._memory_capsule_check(root, proof_root),
            self._cartridge_replay_check(cartridge_id, root, manifest, proof_root),
            self._visual_hashhop_check(proof_root),
            self._standard_benchmark_check(proof_root),
            self._repository_input_check(proof_root),
            self._runtime_profile_check(proof_root),
            self._research_module_check(proof_root),
            self._learned_memory_recall_check(cartridge_id, root, proof_root),
            self._memory_dna_check(root, manifest, proof_root),
            self._cache_trace_check(proof_root),
            self._visual_contradiction_check(proof_root),
        ]
        # A deferred or removed check is neither a failure nor a pass: the suite is only as green as the checks that ran, because "passed" would claim a proof that never ran.
        failed = [check for check in checks if check.status == "failed"]
        unrun = [check for check in checks if check.status in ("deferred", "removed")]
        status: Literal["passed", "failed", "deferred"] = (
            "failed" if failed else ("deferred" if unrun else "passed")
        )
        report = ProofSuiteReport(
            proof_id=proof_id,
            cartridge_id=cartridge_id,
            status=status,
            checks=checks,
            artifacts={},
            dna_before=dna_before,
            dna_after=dna_before,
        )
        report_path = proof_root / "proof_suite.json"
        report_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        report.artifacts = relative_artifacts(proof_root)
        report_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        attached_manifest = self.cartridges.attach_eval_proof(cartridge_id, proof_root)
        report.dna_after = attached_manifest.dna
        report_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        cartridge_report = root / "eval_proofs" / proof_id / "proof_suite.json"
        cartridge_report.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        return report

    def runtime_generation_proof(self) -> ProofCheck:
        proof_id = f"runtime_generation_{secrets.token_hex(8)}"
        proof_root = self.settings.data_dir / "eval_proofs" / proof_id
        proof_root.mkdir(parents=True, exist_ok=True)
        return self._runtime_generation_check(proof_root)

    def visual_contradiction_proof(self) -> ProofCheck:
        proof_id = f"visual_contradiction_{secrets.token_hex(8)}"
        proof_root = self.settings.data_dir / "eval_proofs" / proof_id
        proof_root.mkdir(parents=True, exist_ok=True)
        return self._visual_contradiction_check(proof_root)

    def latest(self) -> ProofSuiteReport | None:
        proof_root = self.settings.data_dir / "eval_proofs"
        reports = sorted(
            proof_root.glob("prd_proof_suite_*/proof_suite.json"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if not reports:
            return None
        return ProofSuiteReport.model_validate_json(reports[0].read_text(encoding="utf-8"))

    def _proof_id(self, cartridge_id: str, dna: str | None) -> str:
        raw = f"{cartridge_id}:{dna}:{secrets.token_hex(8)}"
        return f"prd_proof_suite_{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]}"
