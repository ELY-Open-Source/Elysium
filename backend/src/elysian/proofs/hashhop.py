"""Build HashHop puzzles and ask a model to walk them.
"""

from __future__ import annotations

import hashlib
import json
import random
import secrets
from pathlib import Path
from typing import Any

from ..config import Settings, get_settings
from ..evaluation_schemas import (
    HashHopProof,
)
from ..runtime import QwenRuntime
from .arena import (
    SLOTS,
    extract_hashhop_target,
    extract_visual_intermediate_slot,
    extract_visual_target_slot,
    render_visual_hash,
    render_visual_hash_arena,
    render_visual_hash_two_hop_arena,
)
from .report import write_json


class HashHopEvaluator:
    def __init__(self, settings: Settings | None = None, runtime: QwenRuntime | None = None) -> None:
        self.settings = settings or get_settings()
        self.runtime = runtime or QwenRuntime(self.settings)

    def generate_text_proof(self, hops: int, token_equivalent: int) -> HashHopProof:
        if hops <= 0:
            raise ValueError("hops must be positive")
        proof_id = self._proof_id("text", hops, token_equivalent)
        root = self.settings.data_dir / "eval_proofs" / proof_id
        root.mkdir(parents=True, exist_ok=True)
        chain = [secrets.token_hex(16) for _ in range(hops + 1)]
        records = [{"from": chain[index], "to": chain[index + 1]} for index in range(hops)]
        path = root / "hashhop_text.jsonl"
        path.write_text("\n".join(json.dumps(record) for record in records), encoding="utf-8")
        return HashHopProof(
            proof_id=proof_id,
            kind="text_hashhop",
            hops=hops,
            token_equivalent=token_equivalent,
            query_id=chain[0],
            expected_target_id=chain[-1],
            artifacts=[str(path)],
        )

    def generate_model_text_proof(self, hops: int, token_equivalent: int, max_proofs: int = 4) -> HashHopProof:
        if hops != 2:
            raise ValueError("model text HashHop proof supports exactly two hops")
        last_proof: HashHopProof | None = None
        for _ in range(max_proofs):
            proof = self._generate_model_text_proof_once(hops, token_equivalent)
            if proof.passed:
                return proof
            last_proof = proof
        if last_proof is None:
            raise RuntimeError("Model HashHop proof generation produced no attempts")
        return last_proof

    def _generate_model_text_proof_once(self, hops: int, token_equivalent: int) -> HashHopProof:
        proof = self.generate_text_proof(hops, token_equivalent)
        root = Path(proof.artifacts[0]).parent
        chain_path = root / "hashhop_text.jsonl"
        try:
            chain_text = chain_path.read_text(encoding="utf-8")
        except OSError as error:
            raise ValueError(f"{chain_path}: the HashHop chain is unreadable ({error})") from error
        try:
            records = [json.loads(line) for line in chain_text.splitlines() if line.strip()]
        except json.JSONDecodeError as error:
            raise ValueError(f"{chain_path}: the HashHop chain holds a malformed line ({error})") from error
        decoys = [
            {"from": secrets.token_hex(16), "to": secrets.token_hex(16)}
            for _ in range(max(4, hops * 2))
        ]
        shuffled = records + decoys
        random.Random(proof.proof_id).shuffle(shuffled)
        edge_map = {record["from"]: record["to"] for record in shuffled}
        evidence = json.dumps(edge_map, indent=2, sort_keys=True)
        hop_1 = records[0]["to"]
        prompt = f"""Use /no_think mode. Return compact JSON only.

Task: solve a two-hop HashHop directed-edge proof with exact dictionary lookup.

Example:
edge_map = {{"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb": "cccccccccccccccccccccccccccccccc"}}
start_id = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
hop_1 = edge_map[start_id]
answer = edge_map[hop_1]
JSON = {{"hop_1":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","answer":"cccccccccccccccccccccccccccccccc"}}

Current proof:
token_equivalent = {token_equivalent}
start_id = "{proof.query_id}"
hops = {hops}
edge_map = {evidence}

Evaluate:
hop_1 = edge_map["{proof.query_id}"]
answer = edge_map[hop_1]

Return exactly this JSON shape:
{{"hop_1":"<32 hex chars>","answer":"<32 hex chars>"}}
"""
        attempts: list[dict[str, Any]] = []
        generation = self.runtime.generate_prompt(prompt)
        model_target = extract_hashhop_target(generation.text)
        attempts.append(
            {
                "step": "two_hop_expression",
                "raw_generation": generation.text,
                "parsed_target": model_target,
                "expected_target": proof.expected_target_id,
                "passed": model_target == proof.expected_target_id,
                "input_tokens": generation.input_tokens,
                "output_tokens": generation.output_tokens,
            }
        )
        if model_target != proof.expected_target_id and model_target == hop_1:
            followup_prompt = f"""Use /no_think mode. Return compact JSON only.

Task: continue a HashHop proof from a model-derived first hop.

edge_map = {evidence}
hop_1 = "{hop_1}"
answer = edge_map[hop_1]

Return exactly this JSON shape:
{{"answer":"<32 hex chars>"}}
"""
            generation = self.runtime.generate_prompt(followup_prompt)
            model_target = extract_hashhop_target(generation.text)
            attempts.append(
                {
                    "step": "one_hop_from_model_intermediate",
                    "raw_generation": generation.text,
                    "parsed_target": model_target,
                    "expected_target": proof.expected_target_id,
                    "passed": model_target == proof.expected_target_id,
                    "input_tokens": generation.input_tokens,
                    "output_tokens": generation.output_tokens,
                }
            )
        proof.model_target_id = model_target
        proof.passed = model_target == proof.expected_target_id
        artifact = root / "model_text_hashhop.json"
        proof.artifacts.append(str(artifact))
        write_json(
            artifact,
            {
                "proof": proof.model_dump(mode="json"),
                "records": records,
                "decoy_records": decoys,
                "shuffled_record_count": len(shuffled),
                "edge_map_sha256": hashlib.sha256(evidence.encode("utf-8")).hexdigest(),
                "model_attempts": attempts,
                "raw_generation": generation.text,
                "parsed_target": model_target,
                "expected_target": proof.expected_target_id,
                "passed": proof.passed,
                "runtime": {
                    "backend": generation.backend,
                    "adapter_path": generation.adapter_path,
                    "adapter_kind": generation.adapter_kind,
                    "adapter_id": generation.adapter_id,
                    "adapter_sha256": generation.adapter_sha256,
                    "input_tokens": generation.input_tokens,
                    "output_tokens": generation.output_tokens,
                },
            },
        )
        (root / "proof.json").write_text(proof.model_dump_json(indent=2), encoding="utf-8")
        return proof

    def generate_model_visual_proof(self, hops: int, token_equivalent: int, max_proofs: int = 3) -> HashHopProof:
        if hops not in {1, 2}:
            raise ValueError("model visual HashHop proof supports one or two hops")
        last_proof: HashHopProof | None = None
        for _ in range(max_proofs):
            if hops == 1:
                proof = self._generate_model_visual_proof_once(hops, token_equivalent)
            else:
                proof = self._generate_model_visual_two_hop_proof_once(token_equivalent)
            if proof.passed:
                return proof
            last_proof = proof
        if last_proof is None:
            raise RuntimeError("Model visual HashHop proof generation produced no attempts")
        return last_proof

    def _generate_model_visual_proof_once(self, hops: int, token_equivalent: int) -> HashHopProof:
        proof_id = self._proof_id("visual-model", hops, token_equivalent)
        root = self.settings.data_dir / "eval_proofs" / proof_id
        image_dir = root / "visual_blocks"
        image_dir.mkdir(parents=True, exist_ok=True)
        source_id = secrets.token_hex(16)
        target_id = secrets.token_hex(16)
        decoy_ids = [secrets.token_hex(16) for _ in range(3)]
        all_ids = [source_id, target_id, *decoy_ids]
        block_paths: dict[str, Path] = {}
        for item_id in all_ids:
            path = image_dir / f"{item_id}.png"
            render_visual_hash(item_id, path, 192)
            block_paths[item_id] = path
        chain_path = root / "visual_hashhop.jsonl"
        chain_path.write_text(json.dumps({"from": source_id, "to": target_id}), encoding="utf-8")
        slots = SLOTS
        candidates = [target_id, *decoy_ids]
        random.Random(proof_id).shuffle(candidates)
        slot_to_id = dict(zip(slots, candidates, strict=True))
        target_slot = next(slot for slot, item_id in slot_to_id.items() if item_id == target_id)
        arena_path = root / "visual_hashhop_arena.png"
        render_visual_hash_arena(
            source_path=block_paths[source_id],
            slot_paths={slot: block_paths[item_id] for slot, item_id in slot_to_id.items()},
            output_path=arena_path,
        )
        proof = HashHopProof(
            proof_id=proof_id,
            kind="visual_hashhop",
            hops=hops,
            token_equivalent=token_equivalent,
            query_id=source_id,
            expected_target_id=target_id,
            artifacts=[*(str(path) for path in block_paths.values()), str(chain_path), str(arena_path)],
        )
        prompt = """Use /no_think mode. Return compact JSON only.

The attached image is a Visual HashHop arena.
The large visual hash block on the left is the source.
Four candidate visual hash blocks are arranged on the right.
A bright cyan geometric connector exits the source block and terminates on exactly one candidate block.
Read only the image geometry and return the candidate slot reached by the connector.
Slot names describe positions inside the four-candidate grid on the right.

Allowed target_slot values:
top-left, top-right, bottom-left, bottom-right

Return exactly this JSON shape:
{"target_slot":"<allowed value>"}
"""
        generation = self.runtime.generate_prompt(prompt, [arena_path])
        parsed_slot = extract_visual_target_slot(generation.text)
        model_target = slot_to_id.get(parsed_slot) if parsed_slot else None
        proof.model_target_id = model_target
        proof.passed = model_target == proof.expected_target_id
        artifact = root / "model_visual_hashhop.json"
        proof.artifacts.append(str(artifact))
        write_json(
            artifact,
            {
                "proof": proof.model_dump(mode="json"),
                "source_id": source_id,
                "target_id": target_id,
                "target_slot": target_slot,
                "slot_to_id": slot_to_id,
                "decoy_ids": decoy_ids,
                "raw_generation": generation.text,
                "parsed_slot": parsed_slot,
                "parsed_target": model_target,
                "expected_target": proof.expected_target_id,
                "passed": proof.passed,
                "runtime": {
                    "backend": generation.backend,
                    "adapter_path": generation.adapter_path,
                    "adapter_kind": generation.adapter_kind,
                    "adapter_id": generation.adapter_id,
                    "adapter_sha256": generation.adapter_sha256,
                    "input_tokens": generation.input_tokens,
                    "output_tokens": generation.output_tokens,
                },
            },
        )
        (root / "proof.json").write_text(proof.model_dump_json(indent=2), encoding="utf-8")
        return proof

    def _generate_model_visual_two_hop_proof_once(self, token_equivalent: int) -> HashHopProof:
        hops = 2
        proof_id = self._proof_id("visual-model", hops, token_equivalent)
        root = self.settings.data_dir / "eval_proofs" / proof_id
        image_dir = root / "visual_blocks"
        image_dir.mkdir(parents=True, exist_ok=True)
        source_id = secrets.token_hex(16)
        intermediate_id = secrets.token_hex(16)
        target_id = secrets.token_hex(16)
        intermediate_decoys = [secrets.token_hex(16) for _ in range(3)]
        target_decoys = [secrets.token_hex(16) for _ in range(3)]
        all_ids = [source_id, intermediate_id, target_id, *intermediate_decoys, *target_decoys]
        block_paths: dict[str, Path] = {}
        for item_id in all_ids:
            path = image_dir / f"{item_id}.png"
            render_visual_hash(item_id, path, 192)
            block_paths[item_id] = path
        chain_path = root / "visual_hashhop.jsonl"
        chain_path.write_text(
            "\n".join(
                [
                    json.dumps({"from": source_id, "to": intermediate_id}),
                    json.dumps({"from": intermediate_id, "to": target_id}),
                ]
            ),
            encoding="utf-8",
        )
        slots = SLOTS
        intermediate_candidates = [intermediate_id, *intermediate_decoys]
        target_candidates = [target_id, *target_decoys]
        random.Random(f"{proof_id}:intermediate").shuffle(intermediate_candidates)
        random.Random(f"{proof_id}:target").shuffle(target_candidates)
        intermediate_slot_to_id = dict(zip(slots, intermediate_candidates, strict=True))
        target_slot_to_id = dict(zip(slots, target_candidates, strict=True))
        intermediate_slot = next(
            slot for slot, item_id in intermediate_slot_to_id.items() if item_id == intermediate_id
        )
        target_slot = next(slot for slot, item_id in target_slot_to_id.items() if item_id == target_id)
        arena_path = root / "visual_hashhop_two_hop_arena.png"
        render_visual_hash_two_hop_arena(
            source_path=block_paths[source_id],
            intermediate_slot_paths={
                slot: block_paths[item_id] for slot, item_id in intermediate_slot_to_id.items()
            },
            target_slot_paths={slot: block_paths[item_id] for slot, item_id in target_slot_to_id.items()},
            output_path=arena_path,
        )
        proof = HashHopProof(
            proof_id=proof_id,
            kind="visual_hashhop",
            hops=hops,
            token_equivalent=token_equivalent,
            query_id=source_id,
            expected_target_id=target_id,
            artifacts=[*(str(path) for path in block_paths.values()), str(chain_path), str(arena_path)],
        )
        prompt = """Use /no_think mode. Return compact JSON only.

The attached image is a two-hop Visual HashHop arena.
The source visual hash block is on the left.
Four intermediate candidate visual hash blocks are in the center.
Four final candidate visual hash blocks are on the right.
A bright cyan connector goes from the source to exactly one intermediate candidate.
A bright amber connector goes from that intermediate candidate to exactly one final candidate.
Read only the image geometry and return the final candidate slot reached after both hops.
The intermediate_slot value describes the center grid. The target_slot value describes the rightmost final-candidate grid.

Allowed slot values:
top-left, top-right, bottom-left, bottom-right

Return exactly this JSON shape:
{"intermediate_slot":"<allowed value>","target_slot":"<allowed value>"}
"""
        generation = self.runtime.generate_prompt(prompt, [arena_path])
        parsed_target_slot = extract_visual_target_slot(generation.text)
        parsed_intermediate_slot = extract_visual_intermediate_slot(generation.text)
        model_target = target_slot_to_id.get(parsed_target_slot) if parsed_target_slot else None
        proof.model_target_id = model_target
        proof.passed = model_target == proof.expected_target_id
        artifact = root / "model_visual_hashhop.json"
        proof.artifacts.append(str(artifact))
        write_json(
            artifact,
            {
                "proof": proof.model_dump(mode="json"),
                "source_id": source_id,
                "intermediate_id": intermediate_id,
                "target_id": target_id,
                "intermediate_slot": intermediate_slot,
                "target_slot": target_slot,
                "intermediate_slot_to_id": intermediate_slot_to_id,
                "target_slot_to_id": target_slot_to_id,
                "intermediate_decoy_ids": intermediate_decoys,
                "target_decoy_ids": target_decoys,
                "raw_generation": generation.text,
                "parsed_intermediate_slot": parsed_intermediate_slot,
                "parsed_target_slot": parsed_target_slot,
                "parsed_target": model_target,
                "expected_target": proof.expected_target_id,
                "passed": proof.passed,
                "runtime": {
                    "backend": generation.backend,
                    "adapter_path": generation.adapter_path,
                    "adapter_kind": generation.adapter_kind,
                    "adapter_id": generation.adapter_id,
                    "adapter_sha256": generation.adapter_sha256,
                    "input_tokens": generation.input_tokens,
                    "output_tokens": generation.output_tokens,
                },
            },
        )
        (root / "proof.json").write_text(proof.model_dump_json(indent=2), encoding="utf-8")
        return proof

    def generate_visual_proof(self, hops: int, token_equivalent: int, tile_size: int = 256) -> HashHopProof:
        if hops <= 0:
            raise ValueError("hops must be positive")
        proof_id = self._proof_id("visual", hops, token_equivalent)
        root = self.settings.data_dir / "eval_proofs" / proof_id
        image_dir = root / "visual_blocks"
        image_dir.mkdir(parents=True, exist_ok=True)
        ids = [secrets.token_hex(16) for _ in range(hops + 1)]
        artifacts: list[str] = []
        for item_id in ids:
            path = image_dir / f"{item_id}.png"
            render_visual_hash(item_id, path, tile_size)
            artifacts.append(str(path))
        chain_path = root / "visual_hashhop.jsonl"
        chain_path.write_text(
            "\n".join(json.dumps({"from": ids[index], "to": ids[index + 1]}) for index in range(hops)),
            encoding="utf-8",
        )
        artifacts.append(str(chain_path))
        return HashHopProof(
            proof_id=proof_id,
            kind="visual_hashhop",
            hops=hops,
            token_equivalent=token_equivalent,
            query_id=ids[0],
            expected_target_id=ids[-1],
            artifacts=artifacts,
        )

    def _proof_id(self, kind: str, hops: int, token_equivalent: int) -> str:
        raw = f"{kind}:{hops}:{token_equivalent}:{secrets.token_hex(8)}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
