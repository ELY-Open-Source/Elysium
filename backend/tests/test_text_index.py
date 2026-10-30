"""Checks for the FTS normalizer, run against a real FTS5 table.

String equality alone would pass a normalizer SQLite cannot use, so every acceptance case
here inserts indexed text and asks the engine the question the user would ask.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from elysian.config import Settings
from elysian.db import Database
from elysian.memory import MemoryService
from elysian.schemas import MemoryOrigin
from elysian.store_search import search_atoms
from elysian.text_index import (
    RAREST_KEEP,
    fts_all_expression,
    fts_expression,
    fts_query,
    fts_terms,
    index_text,
    rare_terms,
)


def _fts(rows: list[str]) -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE VIRTUAL TABLE fts USING fts5(original UNINDEXED, text, tokenize = 'unicode61')")
    connection.executemany("INSERT INTO fts(original, text) VALUES (?, ?)", [(row, index_text(row)) for row in rows])
    return connection


def _hits(connection: sqlite3.Connection, query: str) -> list[str]:
    return [row[0] for row in connection.execute("SELECT original FROM fts WHERE fts MATCH ?", (fts_query(query),))]


def _ranked(connection: sqlite3.Connection, query: str) -> list[str]:
    """Matches in bm25 order: the answer that covers more of the question should come first."""
    return [
        row[0]
        for row in connection.execute(
            "SELECT original FROM fts WHERE fts MATCH ? ORDER BY rank", (fts_query(query),)
        )
    ]


def test_index_text_splits_a_chinese_sentence_into_characters() -> None:
    assert index_text("我们的钥匙放在玄关抽屉里") == "我 们 的 钥 匙 放 在 玄 关 抽 屉 里"


def test_index_text_splits_identifiers_a_user_cannot_guess_the_casing_of() -> None:
    assert index_text("func SearchAtoms") == "func search atoms"
    assert index_text("def search_atoms(self) -> None:") == "def search atoms self none"
    assert index_text("HTTPServer2 listens on 8765") == "http server 2 listens on 8765"


def test_index_text_folds_full_width_letters_that_search_would_miss() -> None:
    assert index_text("Ｓｅａｒｃｈ　Ａｔｏｍｓ") == "search atoms"


def test_fts_query_phrases_cjk_and_prefixes_latin() -> None:
    assert fts_query("钥匙") == '"钥 匙"'
    assert fts_query("search atoms") == '"search"* OR "atoms"*'


def test_a_long_question_reaches_the_answer_that_covers_most_of_its_words() -> None:
    """AND over every word answers a long question with nothing; bm25 picks the best candidate."""
    connection = _fts(
        [
            "PRD requirements prove long context memory, HashHop proof, and adapter training.",
            "The adapter was trained for 29 steps on 37 samples.",
            "Unrelated notes about the weather.",
        ]
    )
    question = "Which Elysian PRD requirements prove long context memory, HashHop, and adapters?"
    hits = [
        row[0]
        for row in connection.execute(
            "SELECT original FROM fts WHERE fts MATCH ? ORDER BY rank", (fts_query(question),)
        )
    ]

    assert hits[0].startswith("PRD requirements prove")
    assert "Unrelated notes about the weather." not in hits


def test_fts_query_refuses_a_query_with_nothing_to_match() -> None:
    for empty in ("", "   ", "?!。"):
        with pytest.raises(ValueError, match="needs at least one searchable word"):
            fts_query(empty)


def test_a_chinese_question_finds_the_chinese_memory() -> None:
    connection = _fts(["我们的钥匙放在玄关抽屉里", "The keys are in the kitchen drawer"])
    assert _hits(connection, "钥匙") == ["我们的钥匙放在玄关抽屉里"]


def test_a_cjk_phrase_will_not_match_its_characters_scattered_apart() -> None:
    connection = _fts(["钥匙在抽屉", "匙 在 钥"])
    assert _hits(connection, "钥匙") == ["钥匙在抽屉"]


def test_an_english_query_finds_the_identifier_it_names() -> None:
    connection = _fts(["func SearchAtoms(ctx context.Context)", "func ListCartridges()"])
    assert _hits(connection, "search atoms") == ["func SearchAtoms(ctx context.Context)"]


def test_a_prefix_reaches_the_word_it_grew_into() -> None:
    connection = _fts(["the atom was forgotten", "unrelated text"])
    assert _hits(connection, "atom") == ["the atom was forgotten"]
    assert _hits(connection, "forg") == ["the atom was forgotten"]


def test_a_mixed_query_ranks_the_memory_holding_both_halves_first() -> None:
    """A query with a Chinese half and an English half must prefer the memory holding both."""
    connection = _fts(["钥匙放在 drawer 里", "钥匙在玄关", "the drawer is empty"])
    ranked = _ranked(connection, "钥匙 drawer")

    assert ranked[0] == "钥匙放在 drawer 里"
    assert set(ranked) == {"钥匙放在 drawer 里", "钥匙在玄关", "the drawer is empty"}


def _library(rows: list[str]) -> sqlite3.Connection:
    """A store shaped like the product's: atoms, its FTS mirror, and the count cache."""
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("CREATE TABLE atoms (atom_id TEXT PRIMARY KEY, text TEXT NOT NULL)")
    connection.execute(
        "CREATE VIRTUAL TABLE atom_fts USING fts5(atom_id UNINDEXED, source, text, tokenize = 'unicode61')"
    )
    connection.execute("CREATE TABLE term_df (term TEXT PRIMARY KEY, documents INTEGER NOT NULL)")
    for index, row in enumerate(rows):
        connection.execute("INSERT INTO atoms (atom_id, text) VALUES (?, ?)", (f"a{index}", row))
        connection.execute(
            "INSERT INTO atom_fts (atom_id, source, text) VALUES (?, ?, ?)",
            (f"a{index}", "", index_text(row)),
        )
    return connection


def _shelf(word: str) -> list[str]:
    return [f"the {other} {word} converter" for other in ("csv", "xml", "json", "html", "yaml")]


def test_a_word_the_library_uses_everywhere_is_dropped_from_the_query() -> None:
    """bm25 scores every row an OR query touches, so a common word buys cost, not answers."""
    rows = _shelf("pdf") + _shelf("docx") + ["the parser follows the hashhop chain"]
    connection = _library(rows)

    kept = rare_terms(connection, fts_terms("the hashhop"))

    assert kept == ["hashhop"], "the word every row carries must not decide how many rows get scored"
    hits = connection.execute(
        "SELECT atoms.text FROM atoms JOIN atom_fts ON atom_fts.atom_id = atoms.atom_id WHERE atom_fts MATCH ?",
        (fts_expression(kept),),
    ).fetchall()
    assert [row[0] for row in hits] == ["the parser follows the hashhop chain"]


def test_a_query_whose_words_are_all_common_keeps_the_rarest_of_them() -> None:
    """Dropping every word would search for nothing, so the least common words answer instead."""
    rows = [f"alpha {other}" for other in ("one", "two", "three", "four", "five")] + [
        f"beta {other}" for other in ("six", "seven")
    ]
    connection = _library(rows)

    kept = rare_terms(connection, ["alpha", "beta"])

    assert len(kept) == min(RAREST_KEEP, 2)
    assert kept == ["beta", "alpha"], "the rarer word must lead"


def test_a_query_of_one_word_is_never_filtered() -> None:
    connection = _library(_shelf("pdf"))

    assert rare_terms(connection, ["the"]) == ["the"], "dropping the only word would leave nothing to match"


def test_a_word_the_library_lacks_leaves_nothing_behind() -> None:
    """A question is a read: a stranger's vocabulary must not grow the store one row per novel word."""
    connection = _library(_shelf("pdf"))

    rare_terms(connection, fts_terms("quixotic pdf"))

    cached = connection.execute("SELECT term FROM term_df").fetchall()
    assert [row[0] for row in cached] == [fts_expression(["pdf"])], (
        "only a word the library actually holds is worth remembering"
    )


def test_an_all_expression_demands_every_word_it_is_given() -> None:
    connection = _library(["the archive thermostat holds eighteen degrees", "the archive is closed"])

    hits = connection.execute(
        "SELECT atom_id FROM atom_fts WHERE atom_fts MATCH ?",
        (fts_all_expression(["archive", "thermostat"]),),
    ).fetchall()

    assert [row[0] for row in hits] == ["a0"], "one shared word must not match a whole sentence"


def test_an_empty_library_keeps_every_term() -> None:
    connection = _library([])

    assert rare_terms(connection, ["the", "hashhop"]) == ["the", "hashhop"]


def test_the_remembered_match_counts_are_voided_by_a_write(tmp_path: Path) -> None:
    """A count is only true of the library it was measured against, so any atom write clears it."""
    settings = Settings(home=tmp_path)
    memory = MemoryService(settings=settings, database=Database(settings))
    for index in range(20):
        memory.remember(f"the converter parses format {index} natively", holder_id="wife", origin=MemoryOrigin.self_)
    search_atoms(memory.db, "the converter", limit=5)

    with memory.db.connect() as connection:
        assert int(connection.execute("SELECT count(*) FROM term_df").fetchone()[0]) > 0

    memory.remember("the parser follows the hashhop chain", holder_id="wife", origin=MemoryOrigin.self_)

    with memory.db.connect() as connection:
        assert int(connection.execute("SELECT count(*) FROM term_df").fetchone()[0]) == 0

    page = search_atoms(memory.db, "hashhop chain", limit=5)
    assert "the parser follows the hashhop chain" in [
        atom.text for atom in memory.db.get_atoms([row[0] for row in page.rows])
    ], "a cleared cache must cost time, not answers"
