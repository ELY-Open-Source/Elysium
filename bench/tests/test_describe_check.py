"""The describe harness reads the bar on test and tunes nothing on it: the halves must be real."""

from bench import describe_check


def test_dev_and_test_partition_the_answerable_suite_and_both_hold_every_modality() -> None:
    groups = describe_check.suites()
    dev = {query.query_id for query in groups["dev"]}
    test = {query.query_id for query in groups["test"]}
    whole = {query.query_id for query in groups["whole"]}

    assert dev.isdisjoint(test)
    assert dev | test == whole, "a query outside both halves would be scored only in the whole row"
    for name in ("dev", "test"):
        assert {query.modality for query in groups[name]} == set(describe_check.MODALITY_ORDER)


def test_a_copy_reads_its_pictures_from_the_corpus_objects(tmp_path) -> None:
    import pytest

    objects = tmp_path / "objects"
    (objects / "images").mkdir(parents=True)
    store = tmp_path / "store"
    store.mkdir()

    describe_check.link_objects(store, objects)
    describe_check.link_objects(store, objects)

    assert (store / "objects").resolve() == objects.resolve(), "linking twice is the same link"
    with pytest.raises(SystemExit, match="no ingested pictures here"):
        describe_check.link_objects(tmp_path / "other", tmp_path / "nowhere")
    stale = tmp_path / "stale"
    (stale / "objects").mkdir(parents=True)
    with pytest.raises(SystemExit, match="already exists and is not a link"):
        describe_check.link_objects(stale, objects)
