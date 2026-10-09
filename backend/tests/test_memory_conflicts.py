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


def _lane(tmp_path, texts: list[str], *, scenario: str = "home") -> tuple[MemoryService, Database]:
    settings = Settings(home=tmp_path, default_holder="wife")
    database = Database(settings)
    database.init()
    service = MemoryService(settings=settings, database=database)
    for text in texts:
        service.remember(text, holder_id="wife", origin=MemoryOrigin.self_, scenario=scenario)
    return service, database


def _search(tmp_path, database: Database, query: str) -> list[str]:
    retrieval = RetrievalService(settings=Settings(home=tmp_path, default_holder="wife"), database=database)
    return [hit.atom.text for hit in retrieval.search(query, filters=SearchFilters(as_holder="wife")).hits]


def test_two_rooms_each_keep_their_own_number(tmp_path) -> None:
    service, database = _lane(tmp_path, ["客厅的恒温器调到 22 度", "卧室的恒温器调到 24 度"])

    assert service.conflicts("wife") == [], "they share the verb 调到 and disagree about nothing"
    assert _search(tmp_path, database, "客厅") == ["客厅的恒温器调到 22 度"], (
        "asking about the living room must not answer with the bedroom's reading"
    )


def test_two_people_each_keep_their_own_count(tmp_path) -> None:
    service, _ = _lane(tmp_path, ["她买了 3 本书", "他买了 5 本书"])

    assert service.conflicts("wife") == [], "two buyers are two facts, not one moving count"


def test_one_router_moving_its_counter_is_a_conflict(tmp_path) -> None:
    service, _ = _lane(tmp_path, ["The router forwards 220 packets", "The router forwards 240 packets"])

    clashes = service.conflicts("wife")

    assert len(clashes) == 1
    assert clashes[0].terms == ["router"], "the subject both memories lead with is what the pair disagrees about"
    assert (clashes[0].older_value, clashes[0].newer_value) == ("220", "240")


def test_the_same_subject_measuring_two_things_still_reads_as_one_quantity(tmp_path) -> None:
    service, _ = _lane(tmp_path, ["恒温器设定 22 度", "恒温器功率 100 瓦"])

    assert len(service.conflicts("wife")) == 1, (
        "the store compares labels, not meanings: 设定 and 功率 both hang off 恒温, so this pair is "
        "recorded as one moving quantity and the holder is the one who settles it"
    )


def test_a_memory_that_leads_with_a_number_has_no_subject_to_conflict_on(tmp_path) -> None:
    service, _ = _lane(tmp_path, ["22 度", "24 度"])

    assert service.conflicts("wife") == [], (
        "the number is all the memory has to name itself with, so the store has no subject it could "
        "call the two one thing and records nothing"
    )


def test_a_qualifier_on_the_subject_reads_as_a_different_thing(tmp_path) -> None:
    service, _ = _lane(tmp_path, ["恒温器调到 22 度", "客厅的恒温器调到 24 度"])

    assert service.conflicts("wife") == [], (
        "the store compares labels, not meanings: adding 客厅 moves the subject, so the update is "
        "kept as a second fact rather than noticed as a disagreement — nothing is hidden, and "
        "supersede is still how the holder says which one stands"
    )


def test_a_year_that_leads_a_memory_names_the_thing_it_counts(tmp_path) -> None:
    service, _ = _lane(tmp_path, ["2026 saw 3 releases", "2027 saw 5 releases"])

    assert service.conflicts("wife") == [], (
        "the year is what the count belongs to, not the quantity that moved: 2026 and 2027 are two "
        "records, and comparing their counts would call every timeline a disagreement"
    )


def test_the_same_year_counting_differently_is_a_conflict(tmp_path) -> None:
    service, _ = _lane(tmp_path, ["2026 saw 3 releases", "2026 saw 5 releases"])

    found = service.conflicts("wife")
    assert [conflict.terms for conflict in found] == [["saw"]], (
        "one year, two counts: the year names the record and the count standing behind it is the "
        "quantity that moved, which is what the holder asked to be told about"
    )
    assert [(conflict.older_value, conflict.newer_value) for conflict in found] == [("3", "5")]


def test_room_numbers_name_the_room_rather_than_measure_it(tmp_path) -> None:
    service, database = _lane(tmp_path, ["Room 3 holds 22 degrees", "Room 4 holds 24 degrees"])

    assert service.conflicts("wife") == [], (
        "a number written onto the subject is part of its name: Room 3 and Room 4 are two rooms, "
        "each steady at its own temperature, and suppressing one would throw away a real fact"
    )
    assert sorted(_search(tmp_path, database, "Room")) == sorted(
        ["Room 3 holds 22 degrees", "Room 4 holds 24 degrees"]
    ), "both rooms stay findable"


def test_two_routers_keep_their_own_counters(tmp_path) -> None:
    service, _ = _lane(tmp_path, ["The router 1 forwards 220 packets", "The router 2 forwards 240 packets"])

    assert service.conflicts("wife") == [], (
        "the counter that identifies the router is not the counter it reports, so each router keeps "
        "its own number the way each room keeps its own temperature"
    )


def test_a_number_past_a_word_is_still_the_value_that_moved(tmp_path) -> None:
    service, _ = _lane(tmp_path, ["The rent is 2200 dollars", "The rent is 2400 dollars"])

    found = service.conflicts("wife")
    assert [conflict.terms for conflict in found] == [["rent"]], (
        "a number standing past a word measures the subject instead of naming it, which is what "
        "keeps the ordinary case — a rent that changed — reaching the holder"
    )
    assert [(conflict.older_value, conflict.newer_value) for conflict in found] == [
        ("2200", "2400")
    ]


def test_a_letter_qualifier_does_not_rename_the_room(tmp_path) -> None:
    service, _ = _lane(tmp_path, ["Room A holds 22 degrees", "Room B holds 24 degrees"])

    assert len(service.conflicts("wife")) == 1, (
        "only a number written onto the subject renames it, so Room A and Room B still read as one "
        "room whose reading moved — the pair is recorded for the holder to settle rather than "
        "silently resolved, and this is the boundary the rule does not cross"
    )
