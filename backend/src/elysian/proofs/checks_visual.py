"""Visual HashHop retrieval, the benchmark registry, and the visual contradiction lens.

Moved out of suite.py so the suite order stays readable; each method is a check the
suite runs, and the suite class mixes these in.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from ..benchmarks import (
    benchmark_prediction_report,
    benchmark_registry_report,
    benchmark_sample_report,
    benchmark_source_report,
)
from ..config import Settings
from ..db import Database
from ..evaluation_schemas import (
    ProofCheck,
)
from ..runtime import QwenRuntime
from ..verifier import VisualContradictionLens

# A fixed puzzle count per hop depth. The old suite re-rolled until the running rate crossed its
from .checks_common import (
    HASHHOP_ATTEMPTS,
    _deferred_without_model,
)
from .contradictions import CORPUS_NAME, corpus_path, load_corpus, scenario_context
from .hashhop import HashHopEvaluator
from .hashhop_verify import (
    collect_model_visual_proofs,
    copy_proof_artifacts,
    hashhop_chain_valid,
    pass_rate,
)
from .report import (
    format_scores,
    write_json,
)


class VisualChecks:
    """Visual HashHop retrieval, the benchmark registry, and the visual contradiction lens."""

    settings: Settings
    db: Database

    def _visual_hashhop_check(self, proof_root: Path) -> ProofCheck:
        artifact = proof_root / "visual_hashhop_suite.json"
        deferred = _deferred_without_model(
            self.settings,
            artifact,
            "Visual HashHop Retrieval",
            "PRD 14.2 requires the model to resolve visual hash hops inside 262K, 1.01M and 100M token contexts.",
            "elysian hashhop visual 1 262144 with ELYSIAN_MODEL_DIR set",
        )
        if deferred is not None:
            return deferred
        proof_settings = self.settings.model_copy(update={"max_new_tokens": 128, "temperature": 0.0})
        runtime = QwenRuntime(proof_settings)
        evaluator = HashHopEvaluator(proof_settings, runtime)
        try:
            base_proofs = [
                evaluator.generate_visual_proof(1, 262_144),
                evaluator.generate_visual_proof(2, 262_144),
                evaluator.generate_visual_proof(1, 1_010_000),
                evaluator.generate_visual_proof(1, 100_000_000),
                evaluator.generate_text_proof(2, 1_010_000),
                evaluator.generate_model_text_proof(2, 1_010_000),
            ]
            model_visual_1hop = collect_model_visual_proofs(evaluator, 1, 262_144, HASHHOP_ATTEMPTS)
            model_visual_2hop = collect_model_visual_proofs(evaluator, 2, 262_144, HASHHOP_ATTEMPTS)
            proofs = base_proofs + model_visual_1hop + model_visual_2hop
        finally:
            runtime.unload()
        payloads: list[dict[str, Any]] = []
        for proof in proofs:
            target = proof_root / "hashhop" / proof.proof_id
            copy_proof_artifacts(proof, target)
            payloads.append(
                {
                    "proof": proof.model_dump(mode="json"),
                    "chain_valid": hashhop_chain_valid(proof),
                    "artifact_dir": str(target),
                }
            )
        artifact = proof_root / "visual_hashhop_suite.json"
        model_solved = [
            item
            for item in payloads
            if item["proof"]["model_target_id"] is not None or item["proof"]["passed"] is not None
        ]
        model_text_solved = [
            proof
            for proof in base_proofs
            if proof.kind == "text_hashhop" and proof.model_target_id is not None
        ]
        model_solved_passed = [item for item in model_solved if item["proof"]["passed"]]
        visual_1hop_rate = pass_rate(model_visual_1hop)
        visual_2hop_rate = pass_rate(model_visual_2hop)
        metrics = {
            "visual_hashhop_262k_1hop": {
                "target": 0.90,
                "sample_count": len(model_visual_1hop),
                "passed": sum(1 for proof in model_visual_1hop if proof.passed),
                "pass_rate": visual_1hop_rate,
            },
            "visual_hashhop_262k_2hop": {
                "target": 0.75,
                "sample_count": len(model_visual_2hop),
                "passed": sum(1 for proof in model_visual_2hop if proof.passed),
                "pass_rate": visual_2hop_rate,
            },
        }
        write_json(artifact, {"proofs": payloads, "metrics": metrics})
        valid = (
            all(item["chain_valid"] for item in payloads)
            and bool(model_text_solved)
            and all(bool(proof.passed) for proof in model_text_solved)
            and len(model_visual_1hop) >= 3
            and len(model_visual_2hop) >= 3
            and visual_1hop_rate >= 0.90
            and visual_2hop_rate >= 0.75
        )
        return ProofCheck(
            name="Visual HashHop",
            requirement="PRD 14.2 and 14.3 require Visual HashHop 262K 1-hop, 262K 2-hop, 1M 1-hop, 100M memory retrieval assets, text HashHop 1M 2-hop, model-solved text HashHop evidence, and model-solved visual 1-hop and 2-hop HashHop evidence.",
            status="passed" if valid else "failed",
            evidence=[str(artifact), str(proof_root / "hashhop")],
            detail=(
                f"{len(proofs)} HashHop proofs generated; "
                f"{len(model_solved_passed)}/{len(model_solved)} model-solved proofs passed; "
                f"262K 1-hop={visual_1hop_rate:.2f}, 2-hop={visual_2hop_rate:.2f}"
            ),
        )

    def _standard_benchmark_check(self, proof_root: Path) -> ProofCheck:
        artifact = proof_root / "standard_benchmarks.json"
        deferred = _deferred_without_model(
            self.settings,
            artifact,
            "Standard Benchmark Registry",
            "PRD 14.1 requires MMMU-Pro, OCRBench, MMLongBench-Doc, VideoMME, LongVideoBench, RULER, and LongBench v2 in the evaluation proof chain with real benchmark source metadata, loadable official samples, and local model prediction artifacts.",
            "elysian benchmark-predictions with ELYSIAN_MODEL_DIR set",
        )
        if deferred is not None:
            return deferred
        registry = benchmark_registry_report()
        sources = benchmark_source_report()
        samples = benchmark_sample_report(proof_root / "benchmark_samples")
        predictions = benchmark_prediction_report(self.settings, proof_root / "benchmark_predictions")
        artifact = proof_root / "standard_benchmarks.json"
        source_artifact = proof_root / "standard_benchmark_sources.json"
        sample_artifact = proof_root / "standard_benchmark_samples.json"
        prediction_artifact = proof_root / "standard_benchmark_predictions.json"
        artifact.write_text(registry.model_dump_json(indent=2), encoding="utf-8")
        source_artifact.write_text(sources.model_dump_json(indent=2), encoding="utf-8")
        sample_artifact.write_text(samples.model_dump_json(indent=2), encoding="utf-8")
        prediction_artifact.write_text(predictions.model_dump_json(indent=2), encoding="utf-8")
        required = {
            "MMMU-Pro",
            "OCRBench",
            "MMLongBench-Doc",
            "VideoMME",
            "LongVideoBench",
            "RULER",
            "LongBench v2",
        }
        registered = {benchmark.name for benchmark in registry.benchmarks}
        source_names = {source.name for source in sources.sources if source.status == "ready" and source.sha}
        loaded_sample_names = {sample.name for sample in samples.samples if sample.status == "loaded"}
        gated_sample_names = {sample.name for sample in samples.samples if sample.status == "gated"}
        source_proved_sample_names = {
            sample.name
            for sample in samples.samples
            if sample.status == "loaded" and sample.sample_sha256 and sample.source_dataset and sample.source_sha
        }
        predicted_sample_names = {
            prediction.name for prediction in predictions.predictions if prediction.status == "predicted"
        }
        prediction_scores = {
            prediction.name: prediction.score
            for prediction in predictions.predictions
            if prediction.status == "predicted"
        }
        scored_predictions_pass = {
            "MMMU-Pro",
            "OCRBench",
        } <= {
            name
            for name, score in prediction_scores.items()
            if isinstance(score, (int, float)) and math.isfinite(float(score)) and float(score) >= 0.5
        }
        sample_names = loaded_sample_names | gated_sample_names
        valid = (
            registry.status == "ready"
            and sources.status == "ready"
            and samples.status == "ready"
            and predictions.status == "ready"
            and required <= registered
            and required <= source_names
            and required <= sample_names
            and required <= loaded_sample_names
            and required <= source_proved_sample_names
            and {"MMMU-Pro", "OCRBench"} <= predicted_sample_names
            and scored_predictions_pass
        )
        return ProofCheck(
            name="Standard Benchmark Registry",
            requirement="PRD 14.1 requires MMMU-Pro, OCRBench, MMLongBench-Doc, VideoMME, LongVideoBench, RULER, and LongBench v2 in the evaluation proof chain with real benchmark source metadata, loadable official samples, and local model prediction artifacts.",
            status="passed" if valid else "failed",
            evidence=[str(artifact), str(source_artifact), str(sample_artifact), str(prediction_artifact)],
            detail=(
                f"verified {len(loaded_sample_names)} loadable official benchmark samples; "
                f"{len(predicted_sample_names)} local model sample predictions; "
                f"scores: {format_scores(prediction_scores)}; "
                f"gated samples: {', '.join(sorted(gated_sample_names)) or 'none'}"
            ),
        )

    def _visual_contradiction_check(self, proof_root: Path) -> ProofCheck:
        lens = VisualContradictionLens()
        artifact = proof_root / "visual_contradiction_lens.json"
        path = corpus_path(self.settings.data_dir)
        if path is None:
            write_json(
                artifact,
                {"verdict": "deferred", "why": f"no {CORPUS_NAME} found in {self.settings.data_dir}"},
            )
            return ProofCheck(
                name="Visual Contradiction Lens",
                requirement="PRD 14.2 and 14.3 require the Visual Contradiction Lens to localize cross-version visual conflicts.",
                status="deferred",
                evidence=[str(artifact)],
                detail="no contradiction corpus on disk",
                reason="the check refuses to invent the examples it grades itself on inside the code under test",
                rerun=f"elysian contradiction-corpus, or drop a {CORPUS_NAME} in {self.settings.data_dir}",
            )
        scenarios, corpus_sha256 = load_corpus(path)
        conflicts = [scenario for scenario in scenarios if scenario["expect_drift"]]
        controls = [scenario for scenario in scenarios if not scenario["expect_drift"]]
        detected = 0
        false_positives = 0
        categories: set[str] = set()
        rows: list[dict[str, Any]] = []
        known_categories = (
            "design-token drift",
            "layout drift",
            "typography drift",
            "copy drift",
            "visual-code drift",
            "temporal drift",
        )
        for scenario in scenarios:
            notes = lens.detect(scenario_context(scenario))
            flagged = bool(notes)
            if scenario["expect_drift"]:
                if flagged:
                    detected += 1
                    for note in notes:
                        label = note.split(":", 1)[0]
                        categories.update(category for category in known_categories if label.endswith(category))
            elif flagged:
                false_positives += 1
            rows.append(
                {
                    "scenario": scenario["name"],
                    "expect_drift": scenario["expect_drift"],
                    "flagged": flagged,
                    "notes": notes,
                }
            )
        recall = detected / len(conflicts) if conflicts else 0.0
        false_positive_rate = false_positives / len(controls) if controls else 0.0
        valid = recall >= 0.80 and false_positive_rate == 0.0 and len(categories) >= 5
        write_json(
            artifact,
            {
                "corpus": str(path),
                "corpus_sha256": corpus_sha256,
                "scenarios": rows,
                "metrics": {
                    "conflict_count": len(conflicts),
                    "control_count": len(controls),
                    "detected": detected,
                    "false_positives": false_positives,
                    "recall": recall,
                    "false_positive_rate": false_positive_rate,
                    "detected_categories": sorted(categories),
                    "gate_met": valid,
                },
            },
        )
        return ProofCheck(
            name="Visual Contradiction Lens",
            requirement="PRD 14.2 and 14.3 require the Visual Contradiction Lens to localize cross-version visual conflicts with contradiction detection >= 80% on internal conflict samples and without false positives on consistent samples.",
            status="deferred",
            evidence=[str(artifact)],
            detail=(
                f"measured recall {recall:.2f} on {len(conflicts)} conflict samples, "
                f"false positives {false_positives}/{len(controls)}, "
                f"categories {', '.join(sorted(categories))}"
            ),
            reason=(
                f"the lens is graded on {CORPUS_NAME} (sha256 {corpus_sha256[:16]}…), a corpus this repo "
                "authored, and detects it with five regexes over atom text; a producer grading itself on "
                "its own examples is not evidence, so the number is reported but not claimed"
            ),
            rerun="drop a third-party UI-drift set at $ELYSIAN_HOME/contradiction_scenarios.json (elysian contradiction-corpus writes the default), then elysian visual-contradiction-proof",
        )

