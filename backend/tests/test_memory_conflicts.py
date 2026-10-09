"""Two memories cannot both be true: the store notices, answers with the newer side, and waits.

Settling a disagreement is the holder's act. Until then the store chooses, but it records that
it chose, and it keeps both sides so the choice can be undone.
"""

from __future__ import annotations

from datetime import UTC, datetime

from ely_eye.config import Settings
from ely_eye.db import Database
from ely_eye.memory import MemoryService
from ely_eye.retrieval import RetrievalService
from ely_eye.schemas import MemoryOrigin, SearchFilters

NOW = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
OLD = "恒温器放在书房，设定 22 度"
NEW = "恒温器调到 24 度"


def _pair(tmp_path, *, scenario: str = "home", newer_holder: str = "wife") -> tuple[MemoryService, Database, list[str]]:
    settings = Settings(home=tmp_path, default_holder="wife")
    database = Database(settings)
    database.init()
    service = MemoryService(settings=settings, database=database)
    older = service.remember(OLD, holder_id="wife", origin=MemoryOrigin.self_, scenario=scenario).atom_id
    newer = service.remember(NEW, holder_id=newer_holder, origin=MemoryOrigin.self_, scenario=scenario).atom_id
    return service, database, [older, newer]


def test_a_number_that_changed_leaves_a_conflict_naming_both_sides(tmp_path) -> None:
    service, _, ids = _pair(tmp_path)

    clashes = service.conflicts("wife")

    assert len(clashes) == 1
    record = clashes[0]
    assert (record.older_atom_id, record.newer_atom_id) == (ids[0], ids[1])
    assert record.older_value == "22" and record.newer_value == "24"
    assert record.terms, "the record names what the two memories disagree about"
    assert record.resolved_at is None


def test_repeating_the_same_statement_adds_no_memory_and_no_conflict(tmp_path) -> None:
    service, database, _ = _pair(tmp_path)
    before = len(service.conflicts("wife"))

    service.remember(NEW, holder_id="wife", origin=MemoryOrigin.self_, scenario="home")

    assert database.atom_count() == 2, "the same holder stating the same sentence holds one memory"
    assert len(service.conflicts("wife")) == before, (
        "a repeat cannot manufacture a second disagreement"
    )


def test_a_memory_that_agrees_leaves_nothing_to_settle(tmp_path) -> None:
    settings = Settings(home=tmp_path, default_holder="wife")
    database = Database(settings)
    database.init()
    service = MemoryService(settings=settings, database=database)
    service.remember(OLD, holder_id="wife", origin=MemoryOrigin.self_, scenario="home")

    service.remember("恒温器设定 22 度", holder_id="wife", origin=MemoryOrigin.self_, scenario="home")

    assert service.conflicts("wife") == [], (
        "restating the same reading in other words is agreement, and the rule must not flinch at it"
    )


def test_two_holders_who_disagree_are_not_a_conflict_in_one_memory(tmp_path) -> None:
    service, _, _ = _pair(tmp_path, newer_holder="husband")

    assert service.conflicts("wife") == [], "the husband changing his own mind is not the wife's contradiction"


def test_a_change_in_another_scenario_is_a_different_question(tmp_path) -> None:
    settings = Settings(home=tmp_path, default_holder="wife")
    database = Database(settings)
    database.init()
    service = MemoryService(settings=settings, database=database)
    service.remember(OLD, holder_id="wife", origin=MemoryOrigin.self_, scenario="home")
    service.remember(NEW, holder_id="wife", origin=MemoryOrigin.self_, scenario="office")

    assert service.conflicts("wife") == [], (
        "the office thermostat and the home thermostat are two thermostats"
    )


def test_a_supersede_already_chose_a_side_and_records_no_conflict(tmp_path) -> None:
    service, _, ids = _pair(tmp_path, scenario="")
    before = len(service.conflicts("wife"))

    service.supersede(ids[0], text="恒温器调到 26 度", holder_id="wife")

    assert len(service.conflicts("wife")) == before, (
        "a replacement is a decision, not a disagreement waiting to be settled"
    )


def test_a_disagreement_about_words_rather_than_numbers_is_left_alone(tmp_path) -> None:
    settings = Settings(home=tmp_path, default_holder="wife")
    database = Database(settings)
    database.init()
    service = MemoryService(settings=settings, database=database)
    service.remember("钥匙在玄关抽屉里", holder_id="wife", origin=MemoryOrigin.self_, scenario="home")
    service.remember("钥匙在车里", holder_id="wife", origin=MemoryOrigin.self_, scenario="home")

    assert service.conflicts("wife") == [], (
        "the numeric rule is the one that can be checked; a reworded sentence would fire on every paraphrase"
    )


def test_an_open_conflict_makes_the_store_answer_with_the_newer_side(tmp_path) -> None:
    _, database, ids = _pair(tmp_path)
    retrieval = RetrievalService(settings=Settings(home=tmp_path, default_holder="wife"), database=database)

    hits = retrieval.search("恒温器", filters=SearchFilters(as_holder="wife")).hits

    assert [hit.atom.atom_id for hit in hits] == [ids[1]], (
        "both memories match the words; only the disagreement decides which one answers"
    )


def test_settling_a_conflict_gives_both_sides_back(tmp_path) -> None:
    service, database, ids = _pair(tmp_path)
    retrieval = RetrievalService(settings=Settings(home=tmp_path, default_holder="wife"), database=database)
    clash = service.conflicts("wife")[0]

    assert service.resolve_conflicts([clash.conflict_id], at=NOW) == 1
    assert service.conflicts("wife") == []

    hits = retrieval.search("恒温器", filters=SearchFilters(as_holder="wife")).hits
    assert {hit.atom.atom_id for hit in hits} == set(ids), (
        "a settled disagreement stops the store from choosing; both memories are current again"
    )
    assert database.get_atoms(ids)[0].valid_to is None, "settling is not the same as superseding"


def test_a_conflict_belongs_to_the_memory_it_was_found_in(tmp_path) -> None:
    service, _, ids = _pair(tmp_path)
    assert service.conflicts("wife"), "the disagreement exists before the forget"

    forgotten = service.forget(atom_id=ids[1], reason="the reading was wrong")

    assert forgotten.atoms_deleted == 1
    assert service.conflicts("wife") == [], (
        "one side is gone, so there is nothing left to settle and no ghost row to list"
    )
