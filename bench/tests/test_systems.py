"""Checks for the arm plumbing, so a broken ranking cannot hide behind a green baseline run."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pytest

from bench.systems import (
    ARMS,
    ArmRunner,
    Atom,
    _unit,
    arm_needs,
    fuse,
    load_atoms,
    local_model_dir,
    tokenize,
    top_sources,
)

ATOMS = [
    Atom(atom_id="a1", source_id="src_red", text="red door key"),
    Atom(atom_id="a2", source_id="src_blue", text="blue drawer"),
    Atom(atom_id="a3", source_id="src_red", text="the key hangs on the red door"),
]

# The product names a source by content hash; the benchmark names the same file by
# its corpus id (the source_id above). load_atoms joins the two through sources.path.
PRODUCT_SOURCES = {"prod_red_9f3a": "/fixture/red.png", "prod_blue_1c77": "/fixture/blue.png"}
ATOM_PRODUCT_IDS = ["prod_red_9f3a", "prod_blue_1c77", "prod_red_9f3a"]


def test_tokenize_keeps_cjk_and_words() -> None:
    assert tokenize("钥匙 Key") == ["钥匙", "key"]
    assert tokenize("") == []


def test_top_sources_ranks_by_the_best_atom_of_each_source() -> None:
    scores = np.array([1.0, 5.0, 9.0])
    assert top_sources(scores, ATOMS, 10) == ["src_red", "src_blue"]


def test_top_sources_breaks_ties_on_source_id() -> None:
    scores = np.array([3.0, 3.0, 3.0])
    assert top_sources(scores, ATOMS, 10) == ["src_blue", "src_red"]


def test_top_sources_rejects_a_length_mismatch() -> None:
    with pytest.raises(SystemExit, match="scores has 2 entries for 3 atoms"):
        top_sources(np.array([1.0, 2.0]), ATOMS, 3)


def test_unit_scales_to_zero_one_and_flattens_a_constant() -> None:
    np.testing.assert_allclose(_unit(np.array([0.0, 2.0])), [0.0, 1.0])
    np.testing.assert_allclose(_unit(np.array([7.0, 7.0, 7.0])), [0.0, 0.0, 0.0])


def test_fuse_uses_the_product_weights() -> None:
    fused = fuse(np.array([1.0, 0.0]), np.array([0.0, 1.0]), np.array([0.0, 0.0]))
    assert fused[0] == pytest.approx(0.55)
    assert fused[1] == pytest.approx(0.35)
    assert sum([0.55, 0.35, 0.10]) == pytest.approx(1.0)


def test_graph_only_arm_is_a_constant_and_sorts_by_source_id() -> None:
    runner = ArmRunner("graph_only", ATOMS, Path("/nonexistent"))
    assert runner.rank("key") == ["src_blue", "src_red"]


def test_bm25_arm_finds_the_atom_that_names_the_query() -> None:
    runner = ArmRunner("bm25_only", ATOMS, Path("/nonexistent"))
    assert runner.rank("the key hangs")[0] == "src_red"
    # A query with no tokens has no signal: every score is zero, so the order is source id.
    assert runner.rank("") == ["src_blue", "src_red"]


def test_arm_needs_reports_missing_models_without_crashing(tmp_path: Path) -> None:
    assert arm_needs("bm25_only", tmp_path) is True
    assert arm_needs("dense_only", tmp_path) is False
    (local_model_dir(tmp_path, "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")).mkdir(parents=True)
    assert arm_needs("dense_only", tmp_path) is True
    assert arm_needs("fusion_rerank", tmp_path) is False


def test_arm_needs_rejects_an_unknown_arm() -> None:
    with pytest.raises(SystemExit, match="unknown arm"):
        arm_needs("quantum", Path("/nonexistent"))
    assert "fusion_rerank" in ARMS


def test_local_model_dir_flattens_the_namespace() -> None:
    assert local_model_dir(Path("/m"), "BAAI/bge-reranker-base") == Path("/m/bge-reranker-base")


def make_database(path: Path) -> None:
    """Create the product's atoms and sources tables and put three rows in them."""
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE atoms (atom_id text PRIMARY KEY, source_id text, modality text, source text, time text,"
        " text text, image_ref text, embedding_refs_json text, layout_json text, relations_json text,"
        " trust_json text, token_equivalent integer, metadata_json text)"
    )
    connection.execute("CREATE TABLE sources (source_id text PRIMARY KEY, path text)")
    for atom, product_id in zip(ATOMS, ATOM_PRODUCT_IDS, strict=True):
        connection.execute("INSERT INTO atoms (atom_id, source_id, text) VALUES (?, ?, ?)", (atom.atom_id, product_id, atom.text))
    for source_id, file_path in PRODUCT_SOURCES.items():
        connection.execute("INSERT INTO sources (source_id, path) VALUES (?, ?)", (source_id, file_path))
    connection.commit()
    connection.close()


def fake_source_map() -> dict[str, str]:
    """Stand in for the frozen corpus index: file path to the corpus id the gold uses."""
    return {PRODUCT_SOURCES[pid]: atom.source_id for atom, pid in zip(ATOMS, ATOM_PRODUCT_IDS, strict=True)}


def test_load_atoms_returns_every_row_in_a_stable_order(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("bench.systems.source_map", fake_source_map)
    db = tmp_path / "ely_eye.sqlite"
    make_database(db)
    loaded = load_atoms(db)
    assert [atom.atom_id for atom in loaded] == ["a1", "a2", "a3"]
    # The database stores the product's content-hash id; the caller gets the corpus id
    # the gold annotations use.
    assert [atom.source_id for atom in loaded] == ["src_red", "src_blue", "src_red"]
    assert loaded[2].text == "the key hangs on the red door"


def test_load_atoms_refuses_an_atom_it_cannot_trace_to_a_corpus_file(tmp_path: Path) -> None:
    db = tmp_path / "ely_eye.sqlite"
    make_database(db)
    with pytest.raises(SystemExit, match="atom paths are not corpus files"):
        load_atoms(db)


def test_load_atoms_fails_fast_on_a_missing_or_unusable_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("bench.systems.source_map", fake_source_map)
    with pytest.raises(SystemExit, match="no merged baseline database"):
        load_atoms(tmp_path / "absent.sqlite")
    no_table = tmp_path / "no_table.sqlite"
    no_table.touch()
    with pytest.raises(SystemExit, match="cannot read the atoms table"):
        load_atoms(no_table)
    empty = tmp_path / "empty.sqlite"
    make_database(empty)
    connection = sqlite3.connect(empty)
    connection.execute("DELETE FROM atoms")
    connection.commit()
    connection.close()
    with pytest.raises(SystemExit, match="atoms table is empty"):
        load_atoms(empty)


def test_percentile_needs_timings_and_a_valid_fraction() -> None:
    runner = ArmRunner("graph_only", ATOMS, Path("/nonexistent"))
    with pytest.raises(SystemExit, match="no timings recorded"):
        runner.percentile(0.5)
    runner.rank("key")
    with pytest.raises(SystemExit, match="percentile must be within"):
        runner.percentile(1.5)
    assert runner.percentile(0.5) >= 0.0


def test_the_dense_model_is_loaded_once_per_process(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The query path used to rebuild the model for every query and measured that as retrieval latency."""
    import sentence_transformers

    from bench import systems

    loaded: list[str] = []

    class FakeModel:
        def __init__(self, path: str, **_kwargs: object) -> None:
            loaded.append(path)

    monkeypatch.setattr(sentence_transformers, "SentenceTransformer", FakeModel)
    systems._MODELS.clear()
    model_dir = tmp_path / "dense"
    model_dir.mkdir()
    try:
        assert systems._sentence_model(model_dir) is systems._sentence_model(model_dir)
        assert loaded == [str(model_dir)]
        with pytest.raises(SystemExit, match="model not downloaded"):
            systems._sentence_model(tmp_path / "missing")
    finally:
        systems._MODELS.clear()


def test_the_cpu_budget_is_pinned_and_reported() -> None:
    """Latency measured with every core available measures the scheduler, so the budget is fixed and printed."""
    import os

    from bench import systems

    budget = systems.machine_facts()["threads_per_query"]
    pinned = {os.environ[name] for name in _THREAD_VARIABLES}
    assert pinned == {str(budget)}
    assert 1 <= budget <= 8


_THREAD_VARIABLES = ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS")
