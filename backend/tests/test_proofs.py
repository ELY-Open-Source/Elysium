"""A proof check reports what it measured: passed, failed, deferred, or removed."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import pytest
from PIL import Image

from elysian.cartridge import CartridgeService
from elysian.config import Settings
from elysian.memory import MemoryService
from elysian.proofs import PRDProofSuite
from elysian.proofs.arena import (
    _slot_boxes,
    render_visual_hash,
    render_visual_hash_arena,
)
from elysian.proofs.checks_common import _deferred_without_model
from elysian.proofs.contradictions import (
    PACKAGED_CORPUS,
    build_contradiction_scenarios,
    load_corpus,
)
from elysian.proofs.table import render_table
from elysian.schemas import MemoryOrigin

# The replay question is fixed inside the suite, so the fixture memory must answer it in words the ranker can match.
PRD_MEMORY = "PRD requirements prove long context memory, HashHop proof, and adapter training."
OTHER_KEYS = "PRD requirements also prove cache invalidation for HashHop proof and adapters."


class Harness:
    """A suite wired to one temporary store, plus the directory its artifacts land in."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.memory = MemoryService(settings=settings)
        self.db = self.memory.db
        self.cartridges = CartridgeService(settings=settings, database=self.db)
        self.suite = PRDProofSuite(settings)
        self.proof_root = settings.data_dir / "eval_proofs" / "test"
        self.proof_root.mkdir(parents=True, exist_ok=True)

    def remember(self, text: str) -> str:
        atom = self.memory.remember(text, holder_id="wife", origin=MemoryOrigin.self_, scenario="home")
        return atom.atom_id

    def cartridge(self, name: str, atom_ids: list[str]) -> str:
        atoms = self.db.get_atoms(atom_ids)
        sources = self.db.get_sources(sorted({atom.source_id for atom in atoms}))
        return self.cartridges.materialize(name, atoms, sources).cartridge_id


@pytest.fixture
def harness(tmp_path: Path, model_dir: Path) -> Harness:
    return Harness(Settings(home=tmp_path / "home", model_dir=model_dir, default_holder="wife"))


def test_a_store_with_nothing_to_ask_fails_the_cache_trace_check(harness: Harness) -> None:
    check = harness.suite._cache_trace_check(harness.proof_root)

    assert check.status == "failed"
    assert "empty store" in check.reason


def test_the_cache_trace_check_requires_a_measured_miss_then_hit(harness: Harness) -> None:
    harness.remember(PRD_MEMORY)

    check = harness.suite._cache_trace_check(harness.proof_root)

    assert check.status == "passed", check.detail
    assert check.reason == ""


def test_the_research_module_check_is_removed_because_it_could_not_fail(
    harness: Harness,
) -> None:
    check = harness.suite._research_module_check(harness.proof_root)

    assert check.status == "removed"
    assert check.reason and check.rerun


def test_the_repository_check_fails_when_the_repository_never_reached_the_store(
    harness: Harness,
) -> None:
    check = harness.suite._repository_input_check(harness.proof_root)

    assert check.status == "failed"
    assert "store" in check.detail or "store" in check.reason


def test_the_replay_check_answers_only_from_the_cartridge_it_mounts(harness: Harness) -> None:
    inside = harness.remember(PRD_MEMORY)
    # A second memory answering the same question but outside the cartridge: an unmounted replay would have found it and called that a cartridge replay.
    harness.remember(OTHER_KEYS)
    cartridge_id = harness.cartridge("keys", [inside])
    manifest = next(
        item for item in harness.cartridges.list_manifests() if item.cartridge_id == cartridge_id
    )

    check = harness.suite._cartridge_replay_check(
        cartridge_id, harness.settings.cartridge_dir / cartridge_id, manifest, harness.proof_root
    )

    assert check.status == "passed", check.detail
    assert harness.cartridges.mount_state().mounted == []


def test_a_check_defers_loudly_when_the_model_it_needs_is_missing(
    tmp_path: Path, model_dir: Path
) -> None:
    without = _deferred_without_model(
        Settings(home=tmp_path / "a"),
        tmp_path / "a" / "artifact.json",
        "Runtime Adapter Binding",
        "PRD 18 requires the trained adapter to run.",
        "elysian proof runtime with model_dir set",
    )
    with_model = _deferred_without_model(
        Settings(home=tmp_path / "b", model_dir=model_dir),
        tmp_path / "b" / "artifact.json",
        "Runtime Adapter Binding",
        "PRD 18 requires the trained adapter to run.",
        "elysian proof runtime with model_dir set",
    )

    assert without is not None and without.status == "deferred"
    assert without.rerun == "elysian proof runtime with model_dir set"
    assert (tmp_path / "a" / "artifact.json").exists()
    assert with_model is None


def test_the_table_shows_the_verdict_counts_and_the_reason_for_each_claim() -> None:
    from elysian.evaluation_schemas import ProofCheck, ProofSuiteReport

    report = ProofSuiteReport(
        proof_id="proof-1",
        cartridge_id="cart-1",
        status="deferred",
        artifacts={},
        checks=[
            ProofCheck(name="Ran", requirement="r", status="passed", evidence=[], detail="measured x"),
            ProofCheck(
                name="Waiting",
                requirement="r",
                status="deferred",
                evidence=[],
                detail="nothing ran",
                reason="no model weights",
                rerun="elysian proof suite",
            ),
        ],
    )

    table = render_table(report)

    assert "counts: failed 0, passed 1, deferred 1, removed 0" in table
    assert "why: no model weights" in table
    assert "rerun: elysian proof suite" in table
    assert table.index("[passed ") < table.index("[deferred")
    assert "[failed" not in table and "[removed" not in table


def test_the_latest_command_prints_the_table_and_exits_by_verdict(
    tmp_path: Path, monkeypatch
) -> None:
    import json

    from typer.testing import CliRunner

    from elysian import cli as cli_module
    from elysian.evaluation_schemas import ProofCheck, ProofSuiteReport

    settings = Settings(home=tmp_path / "home")
    monkeypatch.setattr(cli_module, "get_settings", lambda: settings)
    proof_root = settings.data_dir / "eval_proofs"
    ran = ProofCheck(name="Ran", requirement="r", status="passed", evidence=[], detail="ok")
    cases: list[tuple[str, Literal["failed", "deferred"]]] = [
        ("prd_proof_suite_old", "failed"),
        ("prd_proof_suite_new", "deferred"),
    ]
    for proof_id, status in cases:
        report = ProofSuiteReport(
            proof_id=proof_id,
            cartridge_id="cart-1",
            status=status,
            artifacts={},
            checks=[ran],
        )
        directory = proof_root / proof_id
        directory.mkdir(parents=True)
        (directory / "proof_suite.json").write_text(report.model_dump_json(), encoding="utf-8")

    table = CliRunner().invoke(cli_module.app, ["latest-proof-suite"])
    machine = CliRunner().invoke(cli_module.app, ["latest-proof-suite", "--json"])

    assert table.exit_code == 0
    assert "proof prd_proof_suite_new" in table.stdout
    assert json.loads(machine.stdout)["proof_id"] == "prd_proof_suite_new"

    (proof_root / "prd_proof_suite_new" / "proof_suite.json").write_text(
        ProofSuiteReport(
            proof_id="prd_proof_suite_new",
            cartridge_id="cart-1",
            status="failed",
            artifacts={},
            checks=[ran],
        ).model_dump_json(),
        encoding="utf-8",
    )
    failing = CliRunner().invoke(cli_module.app, ["latest-proof-suite"])

    assert failing.exit_code == 1

    monkeypatch.setattr(cli_module, "get_settings", lambda: Settings(home=tmp_path / "empty"))
    nothing = CliRunner().invoke(cli_module.app, ["latest-proof-suite"])

    assert nothing.exit_code != 0
    assert "no proof suite" in nothing.stdout + nothing.stderr  # says so instead of printing null


def test_the_packaged_corpus_matches_the_scenarios_it_was_written_from() -> None:
    scenarios, digest = load_corpus(PACKAGED_CORPUS)
    built = build_contradiction_scenarios()

    assert [item["name"] for item in scenarios] == [item["name"] for item in built]
    assert [item["expect_drift"] for item in scenarios] == [
        item["expect_drift"] for item in built
    ]
    assert len(scenarios) >= 10 and digest


def test_the_contradiction_check_defers_when_no_corpus_exists_and_names_the_file(
    harness: Harness, monkeypatch
) -> None:
    from elysian.proofs import checks_visual as visual_module

    monkeypatch.setattr(visual_module, "corpus_path", lambda data_dir: None)

    check = harness.suite._visual_contradiction_check(harness.proof_root)

    assert check.status == "deferred"
    assert "contradiction_scenarios.json" in check.rerun
    assert check.detail == "no contradiction corpus on disk"


def test_the_contradiction_check_records_which_corpus_it_graded_against(
    harness: Harness,
) -> None:
    import json

    check = harness.suite._visual_contradiction_check(harness.proof_root)
    artifact = json.loads(
        (harness.proof_root / "visual_contradiction_lens.json").read_text(encoding="utf-8")
    )

    assert check.status == "deferred"  # graded on our own corpus: reported, not claimed
    assert artifact["corpus_sha256"]
    assert len(artifact["metrics"]["detected_categories"]) >= 5, artifact["metrics"]


def test_the_hashhop_arena_marks_no_candidate_as_the_answer(harness: Harness, tmp_path: Path) -> None:
    boxes = _slot_boxes(520, 704, 76, 324, 160)
    tiles = {}
    for slot in boxes:
        path = tmp_path / f"{slot}.png"
        render_visual_hash(slot, path, 160)
        tiles[slot] = path
    output = tmp_path / "arena.png"

    render_visual_hash_arena(tiles["top-left"], tiles, output)

    # Every candidate box carries the same outline: a ring, arrow or highlighted slot would give the answer without reading the tile.
    image = Image.open(output).convert("RGB")
    border_colors = {image.getpixel((box[0] + 2, box[1] + 40)) for box in boxes.values()}
    assert border_colors == {(180, 190, 205)}
