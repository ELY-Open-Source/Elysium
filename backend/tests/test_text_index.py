"""Checks for the FTS normalizer, run against a real FTS5 table.

String equality alone would pass a normalizer SQLite cannot use, so every acceptance case
here inserts indexed text and asks the engine the question the user would ask.
"""

from __future__ import annotations

import sqlite3

import pytest

from ely_eye.text_index import fts_query, index_text


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
    question = "Which Ely-Eye PRD requirements prove long context memory, HashHop, and adapters?"
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
