"""remember / supersede / forget are one writer, and forgetting has to reach what it derived."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from elysium.cache_fabric import CacheFabric
from elysium.cartridge_store import add_membership
from elysium.config import Settings
from elysium.db import Database
from elysium.memory import MemoryService
from elysium.schemas import (
    EvidenceAtom,
    MemoryOrigin,
    Modality,
    SourceRecord,
    TimePrecision,
    TrustScores,
)
from elysium.vector_index import VectorIndex

KEYS = "我们的钥匙放在玄关抽屉里"
NOW = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)


@pytest.fixture
def service(tmp_path: Path) -> MemoryService:
    return MemoryService(settings=Settings(home=tmp_path))


def _seed(database: Database, atom: EvidenceAtom) -> None:
    database.upsert_sources(
        [
            SourceRecord(
                source_id=atom.source_id,
                path="/tmp/seed.txt",
                kind="text",
                mime="text/plain",
                sha256="0" * 64,
                size_bytes=4,
                created_at=NOW,
            )
        ]
    )
    database.upsert_atoms([atom])


def _seed_atom(atom_id: str, source_id: str) -> EvidenceAtom:
    return EvidenceAtom(
        atom_id=atom_id,
        modality=Modality.text,
        source_id=source_id,
        source="seed",
        ingested_at=NOW,
        text=KEYS,
        trust=TrustScores(parser=1.0),
        token_equivalent=6,
        holder_id="wife",
    )


def test_remember_stamps_the_holder_and_refuses_an_ownerless_memory(service: MemoryService) -> None:
    atom = service.remember(KEYS, holder_id="wife", origin=MemoryOrigin.self_, scenario="home")
    assert atom.holder_id == "wife"
    assert atom.origin is MemoryOrigin.self_
    assert atom.source == "memory://wife/home"
    assert atom.atom_id.startswith("mem-")
    assert atom.ingested_at <= datetime.now(UTC)
    assert atom.valid_from is None, "when the statement became true is unknown, not 'now'"
    with pytest.raises(ValueError, match="needs text"):
        service.remember("   ", holder_id="wife", origin=MemoryOrigin.self_)
    with pytest.raises(ValueError, match="needs a holder"):
        service.remember(KEYS, holder_id="  ", origin=MemoryOrigin.self_)


def test_the_same_holder_remembering_the_same_sentence_updates_one_memory(service: MemoryService) -> None:
    service.remember(KEYS, holder_id="wife", origin=MemoryOrigin.self_, scenario="home")
    service.remember(KEYS, holder_id="wife", origin=MemoryOrigin.self_, scenario="home")
    service.remember(KEYS, holder_id="husband", origin=MemoryOrigin.self_, scenario="home")
    assert service.db.atom_count() == 2, "two holders holding one sentence is two memories"


def test_an_event_time_without_its_precision_is_refused(service: MemoryService) -> None:
    with pytest.raises(ValueError, match="needs its precision"):
        service.remember(
            "去年三月我们搬到这里",
            holder_id="wife",
            origin=MemoryOrigin.self_,
            event_time=datetime(2025, 3, 1, tzinfo=UTC),
        )


def test_supersede_closes_the_old_memory_and_keeps_both_rows(service: MemoryService) -> None:
    old = service.remember(KEYS, holder_id="wife", origin=MemoryOrigin.self_, scenario="home")
    new = service.supersede(
        old.atom_id,
        text="钥匙现在在书房第二个抽屉",
        holder_id="wife",
        scenario="home",
        event_time=NOW,
        event_time_precision=TimePrecision.day,
        event_time_source="declared",
    )
    assert new.supersedes == [old.atom_id]
    assert service.db.atom_count() == 2, "the closed memory stays so time travel can answer"
    stored_old = service.db.get_atoms([old.atom_id])[0]
    assert stored_old.valid_to is not None
    with service.db.connect() as connection:
        current = {row["atom_id"] for row in connection.execute("SELECT atom_id FROM v_atoms_current")}
    assert current == {new.atom_id}
    with pytest.raises(ValueError, match="already closed"):
        service.supersede(old.atom_id, text="again", holder_id="wife")
    with pytest.raises(ValueError, match="no such atom"):
        service.supersede("mem-missing:text", text="anything", holder_id="wife")


def test_time_travel_reads_the_memory_that_was_true_then(service: MemoryService) -> None:
    old = service.remember(KEYS, holder_id="wife", origin=MemoryOrigin.self_, scenario="home")
    before = datetime.now(UTC) - timedelta(seconds=1)
    new = service.supersede(old.atom_id, text="钥匙现在在书房第二个抽屉", holder_id="wife")
    assert {atom.atom_id for atom in service.db.atoms_as_of(before)} == {old.atom_id}
    assert {atom.atom_id for atom in service.db.atoms_as_of(datetime.now(UTC) + timedelta(seconds=1))} == {
        new.atom_id
    }


def test_forget_reaches_every_copy_of_a_memory(
    service: MemoryService, fake_embeddings: Callable[[], Any]
) -> None:
    atom = _seed_atom("seed-1:text", "seed-1")
    _seed(service.db, atom)
    service.db.write_evidence_edges(
        [{"from_atom_id": "seed-1:text", "to_atom_id": "other", "relation": "cites", "confidence": 1.0}]
    )
    service.db.log_cache_event(layer="compiler", cache_key="k", event="hit", bytes_estimate=10)
    CacheFabric(service.settings, service.db).write_semantic_cache("compiled-1", {"packed_text": KEYS})
    VectorIndex(service.settings, service.db, fake_embeddings()).sync()

    report = service.forget(atom_id="seed-1:text", reason="the drawer is empty")

    assert report.atoms_deleted == 1
    assert report.edges_deleted == 1
    assert report.cache_entries_cleared == 2
    assert report.vectors_dropped == 1
    assert report.semantic_cache_cleared == 1
    assert not (service.settings.cache_dir / "semantic" / "compiled-1.json").exists()
    with service.db.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 0, (
            "a forgotten memory leaves no record of where it came from"
        )
    assert VectorIndex(service.settings, service.db, fake_embeddings()).stats()["vectors"] == 0
    assert service.db.atom_count() == 0
    with service.db.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM atom_fts").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM evidence_edges").fetchone()[0] == 0
        trace = connection.execute("SELECT layer, event FROM cache_events").fetchall()
    assert [(row["layer"], row["event"]) for row in trace] == [("memory", "invalidated")]


def test_forget_names_the_cartridge_that_exported_the_source(service: MemoryService) -> None:
    atom = _seed_atom("seed-1:text", "seed-1")
    _seed(service.db, atom)
    cartridge_root = service.settings.cartridge_dir / "cart-1"
    cartridge_root.mkdir(parents=True)
    (cartridge_root / "sources.json").write_text(
        '[{"source_id": "seed-1"}, {"source_id": "elsewhere"}]', encoding="utf-8"
    )
    service.db.write_cartridge(
        cartridge_id="cart-1",
        name="one",
        root_path=cartridge_root,
        manifest_json="{}",
        dna="dna",
        token_equivalent=6,
        created_at=NOW,
    )
    add_membership(service.db, "cart-1", ["seed-1:text"])
    report = service.forget(source_id="seed-1")
    assert report.affected_cartridges == [{"cartridge_id": "cart-1", "contains_source": True}]
    with service.db.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM cartridge_atoms").fetchone()[0] == 0, (
            "a cartridge must stop holding a memory that no longer exists"
        )


def test_forget_refuses_a_request_that_names_nothing(service: MemoryService) -> None:
    with pytest.raises(ValueError, match="exactly one"):
        service.forget()
    with pytest.raises(ValueError, match="exactly one"):
        service.forget(atom_id="a", source_id="b")
    with pytest.raises(ValueError, match="nothing to forget"):
        service.forget(atom_id="nope:text")
