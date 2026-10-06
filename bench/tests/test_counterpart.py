"""Behaviour checks for the memory counterparts: scoping, dedup, and invalidation are the whole point."""

from __future__ import annotations

from pathlib import Path

import pytest

from bench.counterpart import (
    Counterpart,
    MemoryItem,
    SourceMeta,
    build_items,
    overlap,
    split_items,
    subject_of,
    supersede,
)
from bench.systems import Atom

MODEL_DIR = Path("/nonexistent-model")


def item(text: str, source_id: str, holder: str, observed_at: str, subject: str = "") -> MemoryItem:
    return MemoryItem(
        item_id=f"{source_id}#0",
        text=text,
        source_id=source_id,
        holder=holder,
        scenario="assistant-memory",
        observed_at=observed_at,
        subject=subject,
        valid_from=observed_at,
    )


def test_split_items_cuts_at_the_length_limit() -> None:
    chunks = split_items("word " * 300)
    assert chunks, "a long text must produce items"
    assert all(len(chunk) <= 400 for chunk in chunks)
    assert split_items("   ") == []


def test_split_items_merges_short_sentences_into_one_item() -> None:
    assert len(split_items("The keys are in the drawer. They are blue.")) == 1


def test_subject_of_needs_a_repeated_content_token() -> None:
    assert subject_of("the camera camera camera") == "camera"
    assert subject_of("a single camera mention") == ""
    assert subject_of("") == ""


def test_overlap_separates_a_restatement_from_a_new_statement() -> None:
    assert overlap("the keys are in the blue drawer", "the keys are in the blue drawer") == 1.0
    assert overlap("the keys are in the blue drawer", "completely unrelated bicycle garage") < 0.5
    assert overlap("", "anything") == 0.0


def test_build_items_dedups_within_a_holder_and_keeps_both_across_holders() -> None:
    index = {
        "src_a": SourceMeta("src_a", "ana", "assistant-memory", "conversation", "2023-01-01T00:00:00+00:00"),
        "src_b": SourceMeta("src_b", "bo", "assistant-memory", "conversation", "2023-01-02T00:00:00+00:00"),
    }
    atoms = [
        Atom(atom_id="a1", source_id="src_a", text="The keys hang on the red door."),
        Atom(atom_id="a2", source_id="src_a", text="The keys hang on the red door."),
        Atom(atom_id="b1", source_id="src_b", text="The keys hang on the red door."),
    ]
    items = build_items(atoms, index)
    assert len(items) == 2
    assert {i.holder for i in items} == {"ana", "bo"}
    assert all(i.item_id.startswith(f"{i.source_id}#") for i in items)


def test_supersede_closes_the_older_statement_about_the_same_subject() -> None:
    older = item("my camera collection is in the attic", "src_1", "ana", "2023-01-01T00:00:00+00:00", "camera")
    newer = item("the bicycle is parked in the garage now", "src_2", "ana", "2023-06-01T00:00:00+00:00", "camera")
    assert supersede([older, newer]) == 1
    assert older.valid_to == "2023-06-01T00:00:00+00:00"
    assert newer.valid_to is None


def test_supersede_leaves_a_restatement_alone() -> None:
    first = item("the keys hang on the red door", "src_1", "ana", "2023-01-01T00:00:00+00:00", "keys")
    again = item("the keys hang on the red door too", "src_2", "ana", "2023-02-01T00:00:00+00:00", "keys")
    assert supersede([first, again]) == 0
    assert first.valid_to is None


def test_supersede_is_scoped_to_one_holder() -> None:
    ana = item("my camera collection is in the attic", "src_1", "ana", "2023-01-01T00:00:00+00:00", "camera")
    bo = item("the bicycle is parked in the garage now", "src_2", "bo", "2023-06-01T00:00:00+00:00", "camera")
    assert supersede([ana, bo]) == 0
    assert ana.valid_to is None


def test_a_query_only_sees_its_own_holders_items() -> None:
    ana = item("the keys hang on the red door", "src_ana", "ana", "2023-01-01T00:00:00+00:00")
    bo = item("the keys hang on the green door", "src_bo", "bo", "2023-01-01T00:00:00+00:00")
    store = Counterpart(name="mem0_flat", temporal=False, items=[ana, bo], model_dir=MODEL_DIR)
    mask = store.visible("ana", None)
    assert [store.items[i].holder for i, seen in enumerate(mask) if seen] == ["ana"]


def test_the_temporal_store_hides_closed_items_and_the_flat_store_does_not() -> None:
    closed = item("the keys hang on the red door", "src_old", "ana", "2023-01-01T00:00:00+00:00")
    closed.valid_to = "2023-06-01T00:00:00+00:00"
    open_item = item("the keys hang on the green door", "src_new", "ana", "2023-06-01T00:00:00+00:00")
    items = [closed, open_item]
    flat = Counterpart(name="mem0_flat", temporal=False, items=items, model_dir=MODEL_DIR)
    temporal = Counterpart(name="zep_temporal", temporal=True, items=items, model_dir=MODEL_DIR)
    as_of = "2023-12-01T00:00:00+00:00"
    assert sum(flat.visible("ana", as_of)) == 2
    assert [store.source_id for i, store in enumerate(temporal.items) if temporal.visible("ana", as_of)[i]] == [
        "src_new"
    ]
    before = "2023-02-01T00:00:00+00:00"
    assert sum(temporal.visible("ana", before)) == 1


def test_percentile_needs_timings() -> None:
    store = Counterpart(name="mem0_flat", temporal=False, items=[], model_dir=MODEL_DIR)
    with pytest.raises(SystemExit, match="no timings recorded"):
        store.percentile(0.5)
