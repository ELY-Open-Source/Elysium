"""Memory tiers: a session reloads in order, a lane rolls up, and what nobody uses steps aside.

Nothing here deletes. Every tier move is reversible, because the store's guess about what
mattered is a guess, and a wrong guess should cost a query, not a memory.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from ely_eye.config import Settings
from ely_eye.db import Database
from ely_eye.memory import MemoryService
from ely_eye.retrieval import RetrievalService
from ely_eye.schemas import MemoryOrigin, SearchFilters

NOW = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
SESSION = "cooking-2026-10"


def _service(tmp_path, holder: str = "wife") -> tuple[MemoryService, Database]:
    settings = Settings(home=tmp_path, default_holder=holder)
    database = Database(settings)
    database.init()
    return MemoryService(settings=settings, database=database), database


def _remember(service: MemoryService, text: str, **kwargs) -> str:
    return service.remember(text, holder_id="wife", origin=MemoryOrigin.self_, **kwargs).atom_id


def test_a_session_comes_back_in_the_order_it_was_recorded(tmp_path) -> None:
    service, _ = _service(tmp_path)
    first = _remember(service, "烤箱要除垢", session_id=SESSION)
    second = _remember(service, "面粉在储物架第二层", session_id=SESSION)

    working = service.working_set("wife", SESSION)

    assert [atom.atom_id for atom in working] == [first, second], (
        "a working set is the session's own timeline, not a ranking of it"
    )
    assert all(atom.session_id == SESSION for atom in working)


def test_a_working_set_refuses_to_guess_which_session_is_working(tmp_path) -> None:
    service, _ = _service(tmp_path)
    _remember(service, "面粉在储物架第二层")

    with pytest.raises(ValueError, match="a working set needs a session"):
        service.working_set("wife", "")


def test_one_session_name_does_not_merge_two_holders(tmp_path) -> None:
    service, _ = _service(tmp_path)
    hers = _remember(service, "面粉在储物架第二层", session_id=SESSION)
    service.remember("车库里有备用钥匙", holder_id="husband", origin=MemoryOrigin.self_, session_id=SESSION)

    assert [atom.atom_id for atom in service.working_set("wife", SESSION)] == [hers], (
        "a shared session name is not a shared memory"
    )


def test_a_lane_rolls_up_once_and_keeps_rolling_from_where_it_stopped(tmp_path) -> None:
    service, database = _service(tmp_path)
    assert service.consolidate("wife", "home") is None, "an empty lane has nothing to summarise"

    _remember(service, "烤箱要除垢", scenario="home")
    _remember(service, "面粉在储物架第二层", scenario="home")
    first = service.consolidate("wife", "home", at=NOW)
    assert first is not None and first.atom_count == 2
    rollup = database.get_atoms([first.rollup_atom_id])[0]
    assert "烤箱要除垢" in rollup.text and "面粉在储物架第二层" in rollup.text

    assert service.consolidate("wife", "home", at=NOW) is None, (
        "the watermark is what stops the same memory from being counted twice"
    )

    _remember(service, "恒温器调到 24 度", scenario="home")
    second = service.consolidate("wife", "home", at=NOW + timedelta(days=1))
    assert second is not None and second.atom_count == 3, (
        "the standing summary grows; it does not start over and forget what it already held"
    )
    grown = database.get_atoms([second.rollup_atom_id])[0]
    assert grown.atom_id == first.rollup_atom_id, "one lane holds one summary, replaced in place"
    assert "烤箱要除垢" in grown.text and "恒温器调到 24 度" in grown.text


def test_another_scenario_is_a_different_lane(tmp_path) -> None:
    service, _ = _service(tmp_path)
    _remember(service, "烤箱要除垢", scenario="home")
    _remember(service, "周报周五交", scenario="work")

    home = service.consolidate("wife", "home", at=NOW)
    assert home is not None and home.atom_count == 1
    work = service.consolidate("wife", "work", at=NOW)
    assert work is not None and work.atom_count == 1
    assert home.rollup_atom_id != work.rollup_atom_id


def test_the_archive_rule_states_its_own_terms_and_can_be_read_before_it_acts(tmp_path) -> None:
    service, database = _service(tmp_path)
    forgotten = _remember(service, "前租户的 wifi 密码")
    valued = _remember(service, "妈妈的生日是 3 月 4 日", importance=0.9)
    future = NOW + timedelta(days=365)

    preview = service.archive_stale(older_than_days=0, max_importance=0.5, at=future, dry_run=True)
    assert preview.dry_run and preview.atom_ids == [forgotten]
    assert "recorded before" in preview.rule, "the rule is stated, not hidden in a decay curve"
    assert service.archived() == []

    moved = service.archive_stale(older_than_days=0, max_importance=0.5, at=future)
    assert moved.atom_ids == [forgotten] and not moved.dry_run
    assert [atom.atom_id for atom in service.archived("wife")] == [forgotten]
    assert database.get_atoms([forgotten])[0].archived_at is not None
    assert database.get_atoms([valued])[0].archived_at is None, (
        "a memory somebody marked important is not the archive's to move"
    )
    assert database.atom_count() == 2, "the archive steps a memory aside; it does not erase it"


def test_an_archive_that_moves_nothing_says_so_rather_than_reporting_a_win(tmp_path) -> None:
    service, _ = _service(tmp_path)
    _remember(service, "烤箱要除垢")

    moved = service.archive_stale(older_than_days=365, at=NOW)

    assert moved.atom_ids == [], "a memory recorded yesterday is not older than a year"


def test_restoring_brings_the_memory_back_to_the_current_tier(tmp_path) -> None:
    service, database = _service(tmp_path)
    atom_id = _remember(service, "前租户的 wifi 密码")
    service.archive_stale(older_than_days=0, at=NOW + timedelta(days=365))

    assert service.restore([atom_id]) == 1
    assert service.archived() == []
    assert database.get_atoms([atom_id])[0].archived_at is None

    with pytest.raises(ValueError, match="restore needs atom ids"):
        service.restore([])


def test_a_search_counts_the_memory_it_handed_back(tmp_path) -> None:
    service, database = _service(tmp_path)
    settings = Settings(home=tmp_path, default_holder="wife")
    retrieval = RetrievalService(settings=settings, database=database)
    atom_id = _remember(service, "我们的钥匙放在玄关抽屉里")

    hits = retrieval.search("钥匙", filters=SearchFilters(as_holder="wife")).hits
    assert any(hit.atom.atom_id == atom_id for hit in hits)

    used = database.get_atoms([atom_id])[0]
    assert used.recall_count == 1, "the store records that this memory was used, which is the only use estimate it has"
    assert used.last_recalled_at is not None

    retrieval.search("钥匙", filters=SearchFilters(as_holder="wife"))
    assert database.get_atoms([atom_id])[0].recall_count == 2


def test_a_memory_a_search_already_returned_is_not_stale(tmp_path) -> None:
    service, database = _service(tmp_path)
    settings = Settings(home=tmp_path, default_holder="wife")
    retrieval = RetrievalService(settings=settings, database=database)
    atom_id = _remember(service, "我们的钥匙放在玄关抽屉里")
    assert retrieval.search("钥匙", filters=SearchFilters(as_holder="wife")).hits

    moved = service.archive_stale(older_than_days=0, at=NOW + timedelta(days=365))

    assert moved.atom_ids == [], (
        "a memory that keeps coming back was used; the archive takes what nobody ever asked for"
    )
    assert database.get_atoms([atom_id])[0].archived_at is None


def test_an_archived_memory_stops_answering_without_leaving_the_store(tmp_path) -> None:
    service, database = _service(tmp_path)
    settings = Settings(home=tmp_path, default_holder="wife")
    retrieval = RetrievalService(settings=settings, database=database)
    atom_id = _remember(service, "我们的钥匙放在玄关抽屉里")

    service.archive_stale(older_than_days=0, at=NOW + timedelta(days=365))

    assert retrieval.search("钥匙", filters=SearchFilters(as_holder="wife")).hits == []
    assert database.get_atoms([atom_id])[0].archived_at is not None, (
        "the row is still there; only the current tier stopped carrying it"
    )


def test_importance_is_a_stated_value_and_not_a_free_number(tmp_path) -> None:
    from pydantic import ValidationError

    from ely_eye.schemas import EvidenceAtom, Modality, TrustScores

    with pytest.raises(ValidationError, match="less than or equal to 1"):
        EvidenceAtom(
            atom_id="mem-1:text",
            modality=Modality.text,
            source_id="mem-1",
            source="memory://wife/home",
            text="恒温器调到 24 度",
            trust=TrustScores(parser=1.0),
            holder_id="wife",
            importance=1.5,
        )
