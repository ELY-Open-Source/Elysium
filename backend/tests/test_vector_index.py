"""The dense index answers from the database, so a memory is findable the moment it is written.

Every test here runs with a stand-in model: what is being proved is the index's freshness and
its boundaries, not the quality of a 500 MB snapshot.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from ely_eye.config import Settings
from ely_eye.db import Database
from ely_eye.memory import MemoryService
from ely_eye.retrieval import RetrievalService
from ely_eye.schemas import MemoryOrigin, SearchFilters
from ely_eye.vector_index import VectorIndex, expected_vectors

KEYS = "我们的钥匙放在玄关抽屉里"
PASSPORT = "护照在书房第二个抽屉"


def _settings(tmp_path: Path, model_id: str = "hash-mini") -> Settings:
    return Settings(home=tmp_path, dense_embeddings_enabled=True, embedding_model_id=model_id)


def _index(settings: Settings, database: Database, fake_embeddings: Callable[[], Any]) -> VectorIndex:
    return VectorIndex(settings, database, fake_embeddings())


def _memory(settings: Settings, database: Database, index: VectorIndex) -> MemoryService:
    return MemoryService(settings, database, vectors=index)


def test_a_memory_written_now_is_findable_now(tmp_path: Path, fake_embeddings: Callable[[], Any]) -> None:
    settings, database = _settings(tmp_path), Database(_settings(tmp_path))
    index = _index(settings, database, fake_embeddings)
    _memory(settings, database, index).remember(KEYS, holder_id="wife", origin=MemoryOrigin.self_)

    hits = index.search(index.embeddings.embed_query(KEYS), 10)

    assert list(hits) == ["mem-" + _digest(KEYS, "wife") + ":text"], "no rebuild step stands between writing and finding"


def _digest(statement: str, holder: str) -> str:
    import hashlib

    return hashlib.sha256(f"{holder}\n{statement}".encode()).hexdigest()[:16]


def test_a_closed_memory_stops_answering(tmp_path: Path, fake_embeddings: Callable[[], Any]) -> None:
    settings, database = _settings(tmp_path), Database(_settings(tmp_path))
    index = _index(settings, database, fake_embeddings)
    memory = _memory(settings, database, index)
    old = memory.remember(KEYS, holder_id="wife", origin=MemoryOrigin.self_)

    assert index.search(index.embeddings.embed_query(KEYS), 10) == {old.atom_id: pytest.approx(1.0)}
    replacement = memory.supersede(old.atom_id, text=PASSPORT, holder_id="wife")

    after = index.search(index.embeddings.embed_query(KEYS), 10)
    assert old.atom_id not in after, "a closed memory stops answering"
    assert set(after) == {replacement.atom_id}


def test_a_rewritten_memory_is_encoded_again(tmp_path: Path, fake_embeddings: Callable[[], Any]) -> None:
    settings, database = _settings(tmp_path), Database(_settings(tmp_path))
    index = _index(settings, database, fake_embeddings)
    atom = _memory(settings, database, index).remember(KEYS, holder_id="wife", origin=MemoryOrigin.self_)
    index.sync()

    rewritten = atom.model_copy(update={"text": PASSPORT})
    database.upsert_atoms([rewritten])
    index.sync()

    stale = index.search(index.embeddings.embed_query(KEYS), 10)
    fresh = index.search(index.embeddings.embed_query(PASSPORT), 10)
    assert stale[rewritten.atom_id] < 0.9, "the old wording still holds the old vector"
    assert fresh[rewritten.atom_id] > 0.99


def test_a_forgetting_leaves_no_vector_behind(tmp_path: Path, fake_embeddings: Callable[[], Any]) -> None:
    settings, database = _settings(tmp_path), Database(_settings(tmp_path))
    index = _index(settings, database, fake_embeddings)
    memory = _memory(settings, database, index)
    memory.remember(KEYS, holder_id="wife", origin=MemoryOrigin.self_)
    index.sync()

    report = memory.forget(atom_id="mem-" + _digest(KEYS, "wife") + ":text", reason="moved house")

    assert report.vectors_dropped == 1
    assert index.stats()["vectors"] == 0


def test_somebody_elses_memory_is_not_mine_to_find(tmp_path: Path, fake_embeddings: Callable[[], Any]) -> None:
    settings, database = _settings(tmp_path), Database(_settings(tmp_path))
    index = _index(settings, database, fake_embeddings)
    memory = _memory(settings, database, index)
    hers_atom = memory.remember(KEYS, holder_id="wife", origin=MemoryOrigin.self_)
    his_atom = memory.remember(PASSPORT, holder_id="husband", origin=MemoryOrigin.self_)
    index.sync()

    hers = index.search(index.embeddings.embed_query(KEYS), 10, as_holder="wife")
    his = index.search(index.embeddings.embed_query(KEYS), 10, as_holder="husband")

    assert set(hers) == {hers_atom.atom_id}
    assert set(his) == {his_atom.atom_id}, "he answers from his own memory, not from hers"


def test_a_shared_memory_is_findable_by_both(tmp_path: Path, fake_embeddings: Callable[[], Any]) -> None:
    from ely_eye.schemas import Visibility

    settings, database = _settings(tmp_path), Database(_settings(tmp_path))
    index = _index(settings, database, fake_embeddings)
    memory = _memory(settings, database, index)
    memory.remember(
        KEYS, holder_id="wife", origin=MemoryOrigin.self_, visibility=Visibility(scope="visible_to", holders=["husband"])
    )
    index.sync()

    assert index.search(index.embeddings.embed_query(KEYS), 10, as_holder="wife")
    assert index.search(index.embeddings.embed_query(KEYS), 10, as_holder="husband")
    assert index.search(index.embeddings.embed_query(KEYS), 10, as_holder="daughter") == {}


def test_a_cartridge_scope_cannot_be_walked_around(tmp_path: Path, fake_embeddings: Callable[[], Any]) -> None:
    from datetime import UTC, datetime

    from ely_eye import cartridge_store

    settings, database = _settings(tmp_path), Database(_settings(tmp_path))
    index = _index(settings, database, fake_embeddings)
    memory = _memory(settings, database, index)
    kept = memory.remember(KEYS, holder_id="wife", origin=MemoryOrigin.self_)
    other = memory.remember(PASSPORT, holder_id="wife", origin=MemoryOrigin.self_)
    index.sync()
    database.write_cartridge(
        cartridge_id="cart-1",
        name="household",
        root_path=tmp_path / "cart-1",
        manifest_json="{}",
        dna="d" * 64,
        token_equivalent=1,
        created_at=datetime(2026, 5, 1, tzinfo=UTC),
    )
    cartridge_store.add_membership(database, "cart-1", [kept.atom_id])

    hits = index.search(index.embeddings.embed_query(KEYS + " " + PASSPORT), 10, cartridge_ids=["cart-1"])

    assert set(hits) == {kept.atom_id}, "the scope is applied inside the engine, not after it"
    assert other.atom_id not in hits


def test_a_different_model_rebuilds_instead_of_mixing_vectors(tmp_path: Path, fake_embeddings: Callable[[], Any]) -> None:
    settings, database = _settings(tmp_path), Database(_settings(tmp_path))
    index = _index(settings, database, fake_embeddings)
    _memory(settings, database, index).remember(KEYS, holder_id="wife", origin=MemoryOrigin.self_)
    index.sync()
    assert index.stats()["vectors"] == 1

    swapped = VectorIndex(_settings(tmp_path, model_id="other-model"), database, fake_embeddings())
    swapped.sync()

    facts = swapped.stats()
    assert facts["model"] == "other-model"
    assert facts["vectors"] == 1, "the table was rebuilt, not appended to"


def test_a_picture_with_no_words_is_the_other_indexs_job(tmp_path: Path, fake_embeddings: Callable[[], Any]) -> None:
    from datetime import UTC, datetime

    from ely_eye.schemas import EvidenceAtom, Modality, SourceRecord, TrustScores

    settings, database = _settings(tmp_path), Database(_settings(tmp_path))
    index = _index(settings, database, fake_embeddings)
    now = datetime(2026, 5, 1, tzinfo=UTC)
    database.upsert_sources(
        [
            SourceRecord(
                source_id="pic-1",
                path="/tmp/pic.png",
                kind="image",
                mime="image/png",
                sha256="0" * 64,
                size_bytes=4,
                created_at=now,
            )
        ]
    )
    database.upsert_atoms(
        [
            EvidenceAtom(
                atom_id="pic-1:image",
                modality=Modality.image,
                source_id="pic-1",
                source="pic-1",
                ingested_at=now,
                text="",
                image_ref="pic-1",
                trust=TrustScores(parser=1.0),
                token_equivalent=1,
                holder_id="wife",
            )
        ]
    )

    assert index.sync()["encoded"] == 0
    assert expected_vectors(database) == 0
    assert index.stats()["vectors"] == 0, "a wordless picture is the visual index's job"


def test_the_index_survives_a_reopen(tmp_path: Path, fake_embeddings: Callable[[], Any]) -> None:
    settings = _settings(tmp_path)
    first = Database(settings)
    index = _index(settings, first, fake_embeddings)
    _memory(settings, first, index).remember(KEYS, holder_id="wife", origin=MemoryOrigin.self_)
    index.sync()

    reopened = VectorIndex(settings, Database(settings), fake_embeddings())

    assert reopened.stats()["vectors"] == 1
    assert reopened.search(reopened.embeddings.embed_query(KEYS), 10)


def test_a_superseded_memory_keeps_its_vector_but_leaves_the_current_answer_alone(
    tmp_path: Path, fake_embeddings: Callable[[], Any]
) -> None:
    settings, database = _settings(tmp_path), Database(_settings(tmp_path))
    index = _index(settings, database, fake_embeddings)
    memory = _memory(settings, database, index)
    old = memory.remember(KEYS, holder_id="wife", origin=MemoryOrigin.self_)

    replacement = memory.supersede(old.atom_id, text=PASSPORT, holder_id="wife")

    facts = index.stats()
    assert facts["vectors"] == 2, "a closed memory keeps its vector, or a question about the past cannot reach it"
    assert facts["pending"] == 0
    current = index.search(index.embeddings.embed_query(KEYS), 10, as_holder="wife")
    assert list(current) == [replacement.atom_id], "asked now, only the replacement answers"
    then = index.search(index.embeddings.embed_query(KEYS), 10, as_holder="wife", as_of=old.ingested_at.isoformat())
    assert list(then) == [old.atom_id], "asked before the retirement, the old memory is still findable"


def test_a_closed_memory_owes_the_index_a_vector_even_though_it_answers_nothing_now(
    tmp_path: Path, fake_embeddings: Callable[[], Any]
) -> None:
    """`sync` walks the atoms table, not the current view, or an as-of question would find nothing."""
    settings, database = _settings(tmp_path), Database(_settings(tmp_path))
    index = _index(settings, database, fake_embeddings)
    memory = _memory(settings, database, index)
    old = memory.remember(KEYS, holder_id="wife", origin=MemoryOrigin.self_)
    memory.supersede(old.atom_id, text=PASSPORT, holder_id="wife")
    index.drop_atoms([old.atom_id])

    assert index.stats()["pending"] == 1, "the closed memory answers nothing now, but the index still owes it a vector"
    assert index.sync()["encoded"] == 1, "sync re-encodes the closed memory rather than skipping it"
    assert index.stats()["vectors"] == 2


def test_a_store_that_never_built_its_index_says_so_instead_of_stalling_a_search(
    tmp_path: Path, fake_embeddings: Callable[[], Any]
) -> None:
    settings, database = _settings(tmp_path), Database(_settings(tmp_path))
    index = _index(settings, database, fake_embeddings)
    atom = _memory(settings, database, index).remember(KEYS, holder_id="wife", origin=MemoryOrigin.self_)
    index.drop_atoms([atom.atom_id])

    facts = index.stats()
    assert (facts["vectors"], facts["expected"], facts["pending"]) == (0, 1, 1)
    assert index.search(index.embeddings.embed_query(KEYS), 10) == {}, "a search never rebuilds"
    assert index.sync()["encoded"] == 1
    assert index.search(index.embeddings.embed_query(KEYS), 10)


def test_the_dense_leg_hides_what_the_view_hides(tmp_path: Path, fake_embeddings: Callable[[], Any]) -> None:
    """The search repeats the view's currency rules, so the two must keep answering alike."""
    settings, database = _settings(tmp_path), Database(_settings(tmp_path))
    index = _index(settings, database, fake_embeddings)
    atom = _memory(settings, database, index).remember(KEYS, holder_id="wife", origin=MemoryOrigin.self_)
    lapsed = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    with database.connect() as connection:
        connection.execute("UPDATE atoms SET retention_until = ? WHERE atom_id = ?", (lapsed, atom.atom_id))
        visible = [row["atom_id"] for row in connection.execute("SELECT atom_id FROM v_atoms_current")]

    assert atom.atom_id not in visible, "the view has retired the memory"
    assert index.stats()["vectors"] == 1, "the index still holds its vector"
    assert index.search(index.embeddings.embed_query(KEYS), 10) == {}, "a search retires it too"


def test_a_query_asks_for_a_real_number_of_answers(tmp_path: Path, fake_embeddings: Callable[[], Any]) -> None:
    settings, database = _settings(tmp_path), Database(_settings(tmp_path))
    index = _index(settings, database, fake_embeddings)
    with pytest.raises(ValueError, match="positive limit"):
        index.search(index.embeddings.embed_query(KEYS), 0)


def test_search_answers_from_the_index_without_a_rebuild(tmp_path: Path, fake_embeddings: Callable[[], Any]) -> None:
    settings, database = _settings(tmp_path), Database(_settings(tmp_path))
    embeddings = fake_embeddings()
    service = RetrievalService(settings, database)
    service.embeddings = embeddings  # type: ignore[assignment]
    index = VectorIndex(settings, database, embeddings)
    service.vectors = index
    _memory(settings, database, index).remember(KEYS, holder_id="wife", origin=MemoryOrigin.self_)

    result = service.search(KEYS, filters=SearchFilters(as_holder="wife"))

    assert result.hits, "the needle was written and found in the same breath"
    assert result.hits[0].atom.atom_id == "mem-" + _digest(KEYS, "wife") + ":text"
    assert result.hits[0].dense_score > 0.0
