"""Cartridge assets, the memory capsule, replay, DNA, cache trace, and repository coverage.

Moved out of suite.py so the suite order stays readable; each method is a check the
suite runs, and the suite class mixes these in.
"""

from __future__ import annotations

import json
import secrets
import shutil
from pathlib import Path
from typing import Any

from ..cache_fabric import CacheFabric
from ..cartridge import CartridgeService
from ..cartridge_assets import CartridgeAssetService, merkle_root
from ..compiler import ContextCompiler
from ..config import Settings
from ..db import Database
from ..evaluation_schemas import (
    ProofCheck,
)
from ..ingestion_common import SUPPORTED_CODE_EXTENSIONS
from ..ingestion_repository import build_repository_context, find_git_root
from ..schemas import (
    CartridgeManifest,
    RuntimeProfile,
)

# A fixed puzzle count per hop depth. The old suite re-rolled until the running rate crossed its
from .checks_common import (
    _semantic_counters,
)
from .report import (
    compiled_context_digest,
    parquet_row_count,
    read_memory_capsule,
    validated_segment_hash,
    write_json,
)
from .repository_checks import discover_repository_files, project_root


class CartridgeChecks:
    """Cartridge assets, the memory capsule, replay, DNA, cache trace, and repository coverage."""

    settings: Settings
    db: Database
    cartridges: CartridgeService

    def _cartridge_assets_check(
        self,
        cartridge_id: str,
        cartridge_root: Path,
        proof_root: Path,
    ) -> tuple[ProofCheck, CartridgeManifest]:
        report = CartridgeAssetService(self.settings, self.db).finalize(cartridge_id)
        source_report = cartridge_root / "cartridge_assets.json"
        proof_report = proof_root / "cartridge_assets.json"
        shutil.copy2(source_report, proof_report)
        rows = self.db.list_cartridges()
        manifest_json = next(row["manifest_json"] for row in rows if row["cartridge_id"] == cartridge_id)
        manifest = CartridgeManifest.model_validate_json(manifest_json)
        expected = {
            "text_vectors",
            "visual_vectors",
            "kv_snapshots",
            "memory_capsule",
            "memory_capsule_index",
            "ttt_vl_adapter",
            "visual_mtp_head",
            "cartridge_assets",
        }
        by_name = {asset.name: asset for asset in report.assets}
        visual_vectors = by_name.get("visual_vectors")
        memory_capsule = by_name.get("memory_capsule")
        gaps: list[str] = []
        if report.status != "ready":
            gaps.append(f"the asset report says {report.status}")
        absent = sorted(expected - set(manifest.artifacts))
        if absent:
            gaps.append("not registered in the manifest: " + ", ".join(absent))
        empty = [asset.name for asset in report.assets if asset.size_bytes <= 0]
        if empty:
            gaps.append("zero-byte assets: " + ", ".join(empty))
        if visual_vectors is None or visual_vectors.item_count <= 0:
            gaps.append("visual_vectors holds no vectors")
        if memory_capsule is None or memory_capsule.item_count <= 0:
            gaps.append("memory_capsule holds no segments")
        valid = not gaps
        return (
            ProofCheck(
                name="Cartridge Physical Assets",
                requirement="PRD 8.3 requires text vectors, non-empty visual vectors, KV snapshots, a 100M memory capsule, TTT-VL adapter weights, Visual-MTP head weights, and eval proofs inside the Context Cartridge.",
                status="passed" if valid else "failed",
                evidence=[str(proof_report), str(cartridge_root)],
                detail="materialized assets: " + ", ".join(asset.name for asset in report.assets),
                reason="; ".join(gaps),
                rerun="elysian finalize-cartridge <id>, then elysian proof-suite --cartridge-id <id>",
            ),
            manifest,
        )

    def _memory_capsule_check(self, cartridge_root: Path, proof_root: Path) -> ProofCheck:
        capsule_path = cartridge_root / "memory_capsule.json.zst"
        index_path = cartridge_root / "memory_capsule_index.json"
        artifact = proof_root / "memory_capsule.json"
        payload: dict[str, Any] = {
            "capsule_path": str(capsule_path),
            "index_path": str(index_path),
            "status": "failed",
        }
        valid = False
        try:
            capsule = read_memory_capsule(capsule_path)
            index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {}
            raw_segments = capsule.get("segments")
            if not isinstance(raw_segments, list):
                raise ValueError(f"{capsule_path}: the memory capsule carries no segments list")  # noqa: TRY004  # malformed stored data, not a caller type error
            segments: list[dict[str, Any]] = [segment for segment in raw_segments if isinstance(segment, dict)]
            if len(segments) != len(raw_segments):
                raise ValueError(f"{capsule_path}: a memory capsule segment is not an object")
            segment_hashes = [validated_segment_hash(segment) for segment in segments]
            token_total = sum(int(segment.get("token_count") or 0) for segment in segments)
            computed_merkle = merkle_root(segment_hashes)
            valid = (
                capsule.get("format") == "elysian-memory-capsule-v1"
                and int(capsule.get("token_equivalent") or 0) >= self.settings.library_target_tokens
                and int(capsule.get("segment_count") or 0) == len(segments)
                and token_total == int(capsule.get("token_equivalent") or -1)
                and computed_merkle == capsule.get("segment_merkle_root")
                and index.get("segment_merkle_root") == capsule.get("segment_merkle_root")
                and int(index.get("token_equivalent") or 0) == int(capsule.get("token_equivalent") or -1)
                and int(capsule.get("source_atom_count") or 0) > 0
                and all(segment_hashes)
            )
            payload.update(
                {
                    "status": "passed" if valid else "failed",
                    "token_equivalent": capsule.get("token_equivalent"),
                    "segment_count": capsule.get("segment_count"),
                    "source_atom_count": capsule.get("source_atom_count"),
                    "source_token_equivalent": capsule.get("source_token_equivalent"),
                    "segment_merkle_root": capsule.get("segment_merkle_root"),
                    "computed_merkle_root": computed_merkle,
                    "first_segment": segments[0] if segments else None,
                    "last_segment": segments[-1] if segments else None,
                }
            )
        except Exception as exc:  # noqa: BLE001  # a probe records its failure instead of crashing the proof run
            payload["error"] = str(exc)
        write_json(artifact, payload)
        return ProofCheck(
            name="100M Memory Capsule",
            requirement="PRD 2.2, 7.3, 8.3, and 14.3 require a 10M-100M token-equivalent Context Cartridge memory capsule with verifiable retrieval commitments.",
            status="passed" if valid else "failed",
            evidence=[str(artifact), str(capsule_path), str(index_path)],
            detail=(
                f"{payload.get('token_equivalent')} token-equivalent memory capsule with "
                f"{payload.get('segment_count')} committed segments"
            ),
        )

    def _cartridge_replay_check(
        self,
        cartridge_id: str,
        cartridge_root: Path,
        manifest: CartridgeManifest,
        proof_root: Path,
    ) -> ProofCheck:
        atoms_path = cartridge_root / manifest.artifacts["atoms"]
        sources_path = cartridge_root / manifest.artifacts["sources"]
        sparse_path = cartridge_root / manifest.artifacts["sparse_index"]
        graph_path = cartridge_root / manifest.artifacts["temporal_graph"]
        computed_dna = self.cartridges.compute_dna(cartridge_root)
        atom_rows = parquet_row_count(atoms_path)
        try:
            sources = json.loads(sources_path.read_text(encoding="utf-8")) if sources_path.exists() else []
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f"{sources_path}: the cartridge source list is unreadable ({error})") from error
        question = "Which Elysian PRD requirements prove long context memory, HashHop, and adapters?"
        compiler = ContextCompiler(self.settings, self.db)
        artifact = proof_root / "cartridge_replay.json"
        # The replay must come out of the cartridge, so mounting is what makes the cartridge the retrieval scope; an unmounted replay would prove only that compiling is stable.
        try:
            self.cartridges.mount(cartridge_id)
        except ValueError as error:
            # The KV fingerprint gate refuses a cartridge whose model snapshot this machine cannot read; a missing input is not a failed claim, so report the refusal instead of crashing the suite.
            write_json(artifact, {"verdict": "deferred", "why": str(error)})
            return ProofCheck(
                name="Context Cartridge Replay",
                requirement="PRD 14.2 requires the same cartridge to load reproducibly and produce consistent replay evidence.",
                status="deferred",
                evidence=[str(artifact), str(cartridge_root / "manifest.json")],
                detail=str(error),
                reason="the cartridge records a model snapshot this machine cannot verify, so the replay cannot be attempted",
                rerun="set ELYSIAN_MODEL_DIR to the snapshot the cartridge was built against, then elysian proof-suite --cartridge-id <id>",
            )
        try:
            replay_a = compiler.compile(question, RuntimeProfile.library_100m)
            replay_b = compiler.compile(question, RuntimeProfile.library_100m)
        finally:
            self.cartridges.unmount(cartridge_id)
        digest_a = compiled_context_digest(replay_a)
        digest_b = compiled_context_digest(replay_b)
        payload = {
            "cartridge_id": cartridge_id,
            "manifest_atom_count": manifest.atom_count,
            "parquet_atom_count": atom_rows,
            "manifest_source_count": manifest.source_count,
            "source_count": len(sources),
            "dna_manifest": manifest.dna,
            "dna_computed": computed_dna,
            "artifacts": {
                "atoms": str(atoms_path),
                "sources": str(sources_path),
                "sparse_index": str(sparse_path),
                "temporal_graph": str(graph_path),
            },
            "replay": {
                "question": question,
                "digest_a": digest_a,
                "digest_b": digest_b,
                "hit_ids_a": [hit.atom.atom_id for hit in replay_a.hits],
                "hit_ids_b": [hit.atom.atom_id for hit in replay_b.hits],
                "cache_trace_a": replay_a.cache_trace_id,
                "cache_trace_b": replay_b.cache_trace_id,
            },
        }
        artifact = proof_root / "cartridge_replay.json"
        write_json(artifact, payload)
        cartridge_sources = {str(entry.get("source_id", "")) for entry in sources}
        answered_from_cartridge = bool(replay_a.hits) and all(
            hit.atom.source_id in cartridge_sources for hit in replay_a.hits
        )
        valid = (
            atoms_path.exists()
            and sources_path.exists()
            and sparse_path.exists()
            and graph_path.exists()
            and atom_rows == manifest.atom_count
            and len(sources) == manifest.source_count
            and computed_dna == manifest.dna
            and answered_from_cartridge
            and digest_a == digest_b
        )
        return ProofCheck(
            name="Context Cartridge Replay",
            requirement="PRD 14.2 requires the same cartridge to load reproducibly and produce consistent replay evidence.",
            status="passed" if valid else "failed",
            evidence=[str(artifact), str(cartridge_root / "manifest.json")],
            detail=(
                f"{atom_rows} atoms, {len(sources)} sources, replay digest {digest_a}, "
                f"{len(replay_a.hits)} hits answered from the mounted cartridge"
            ),
            rerun="elysian proof-suite --cartridge-id <id>",
        )

    def _repository_input_check(self, proof_root: Path) -> ProofCheck:
        root = project_root()
        files = discover_repository_files(root)
        code_files = [path for path in files if path.suffix.lower() in SUPPORTED_CODE_EXTENSIONS]
        context = build_repository_context(root, files, code_files, find_git_root(root))
        artifact = proof_root / "repository_input.json"
        write_json(artifact, context)
        call_graph = context["code"]["call_graph"]
        git_context = context["git"]
        issue_pr_history = context["issue_pr_history"]
        # Building a context from files on disk is not evidence the repository reached the store; the claim is that it is queryable.
        stored_sources = [source for source in self.db.list_sources() if source.path.startswith(str(root))]
        stored_atoms = self.db.atom_count()
        artifact = proof_root / "repository_input.json"
        payload = dict(context)
        payload["store_evidence"] = {
            "sources_under_project_root": len(stored_sources),
            "source_ids": [source.source_id for source in stored_sources[:20]],
            "atoms_in_store": stored_atoms,
        }
        write_json(artifact, payload)
        valid = (
            context["structure"]["indexed_file_count"] > 0
            and context["code"]["indexed_file_count"] > 0
            and bool(call_graph)
            and bool(git_context.get("available"))
            and bool(git_context.get("recent_commits"))
            and issue_pr_history.get("source") == "local_git_commit_history"
            and bool(stored_sources)
            and stored_atoms > 0
        )
        return ProofCheck(
            name="Repository Input Coverage",
            requirement="PRD 10.1 requires code repository structure indexing, call graph extraction, and issue/PR history association.",
            status="passed" if valid else "failed",
            evidence=[str(artifact)],
            detail=(
                f"{context['structure']['indexed_file_count']} files indexed; "
                f"{context['code']['indexed_file_count']} code files; "
                f"{len(call_graph)} call edges; "
                f"{len(git_context.get('recent_commits') or [])} git commits; "
                f"{len(stored_sources)} sources and {stored_atoms} atoms in the store"
            ),
            reason="" if valid else "the repository context was built but the store holds no atoms for it",
            rerun="elysian ingest . && elysian proof-suite --cartridge-id <id>",
        )

    def _memory_dna_check(
        self,
        cartridge_root: Path,
        manifest: CartridgeManifest,
        proof_root: Path,
    ) -> ProofCheck:
        computed = self.cartridges.compute_dna(cartridge_root)
        payload = {
            "manifest_dna": manifest.dna,
            "computed_dna": computed,
            "formula": "sha256(sorted cartridge artifacts excluding manifest.json)",
            "artifact_count": sum(1 for path in cartridge_root.rglob("*") if path.is_file()),
        }
        artifact = proof_root / "memory_dna.json"
        write_json(artifact, payload)
        return ProofCheck(
            name="Memory DNA",
            requirement="PRD 11.14 requires a reproducible Memory DNA over adapter delta, evidence graph, retrieval index, and eval proofs.",
            status="passed" if manifest.dna == computed else "failed",
            evidence=[str(artifact), str(cartridge_root)],
            detail=f"manifest DNA {manifest.dna}",
        )

    def _cache_trace_check(self, proof_root: Path) -> ProofCheck:
        """Ask the cache the same question twice and require the second answer to be a hit.

        The old check passed when any layer had any row, which a single `forget` could satisfy.
        The claim in PRD 14.2 is that hit, miss, write and replay state are visible, so the check
        compiles a question nobody has asked, compiles it again, and requires the semantic layer's
        counters to move by exactly one miss then one hit.
        """
        compiler = ContextCompiler(self.settings, self.db)
        fabric = CacheFabric(self.settings, self.db)
        probe = self.db.list_atoms(limit=1)
        if not probe:
            artifact = proof_root / "cache_trace.json"
            write_json(artifact, {"verdict": "failed", "why": "the store holds no atoms"})
            return ProofCheck(
                name="Cache Trace",
                requirement="PRD 14.2 requires cache and memory proof with visible hit, miss, write, and replay state.",
                status="failed",
                evidence=[str(artifact)],
                detail="the store holds no atoms, so there is nothing for the cache to answer",
                reason="an empty store answers every question with an empty context, which would make the two compiles agree for the wrong reason",
                rerun="elysian remember or elysian ingest first, then re-run this proof",
            )
        # The nonce keeps the key unique and the quoted text keeps the question answerable, so a pass means the cache served a real context.
        question = f"{probe[0].text[:60]} cache proof {secrets.token_hex(6)}"
        before = _semantic_counters(fabric)
        first = compiler.compile(question, RuntimeProfile.library_100m)
        middle = _semantic_counters(fabric)
        second = compiler.compile(question, RuntimeProfile.library_100m)
        after = _semantic_counters(fabric)
        digest_first = compiled_context_digest(first)
        digest_second = compiled_context_digest(second)
        payload = {
            "question": question,
            "counters": {"before": before, "after_first": middle, "after_second": after},
            "digest_first": digest_first,
            "digest_second": digest_second,
            "cache_trace_first": first.cache_trace_id,
            "cache_trace_second": second.cache_trace_id,
        }
        artifact = proof_root / "cache_trace.json"
        write_json(artifact, payload)
        miss_recorded = middle["miss"] - before["miss"] == 1 and middle["hit"] - before["hit"] == 0
        hit_recorded = after["hit"] - middle["hit"] == 1
        same_answer = digest_first == digest_second and bool(first.hits)
        valid = miss_recorded and hit_recorded and same_answer
        return ProofCheck(
            name="Cache Trace",
            requirement="PRD 14.2 requires cache and memory proof with visible hit, miss, write, and replay state.",
            status="passed" if valid else "failed",
            evidence=[str(artifact)],
            detail=(
                f"semantic layer counters miss {before['miss']}→{middle['miss']}→{after['miss']}, "
                f"hit {before['hit']}→{middle['hit']}→{after['hit']}, replay digest {digest_first}"
            ),
            reason="" if valid else "the second compile was not recorded as a cache hit",
            rerun="elysian proof-suite --cartridge-id <id>",
        )

    def _resolve_cartridge(self, cartridge_id: str | None) -> dict[str, Any]:
        rows = self.db.list_cartridges()
        if not rows:
            raise ValueError("No Context Cartridge is available.")
        if cartridge_id is None:
            return rows[0]
        for row in rows:
            if row["cartridge_id"] == cartridge_id:
                return row
        raise ValueError(f"Unknown cartridge: {cartridge_id}")

