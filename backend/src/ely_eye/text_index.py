"""One normalizer for both sides of the FTS index.

FTS5's unicode61 tokenizer splits on whitespace and punctuation only. It reads
「我们的钥匙放在玄关抽屉里」 as one token and `SearchAtoms` as one token, so a search for
钥匙 or atoms finds nothing and reports it as an empty result. Index and query must run the
same transform; keeping them in one file is what stops them from drifting apart.
"""

from __future__ import annotations

import re
import sqlite3
from unicodedata import normalize

# Han, its extension A block, compatibility ideographs, kana and Hangul syllables: scripts written without spaces, shared by tokenizer and query.
_BLOCKS = ((0x3400, 0x4DBF), (0x4E00, 0x9FFF), (0xF900, 0xFAFF), (0x3040, 0x30FF), (0xAC00, 0xD7AF))
_CJK_CLASS = "".join(f"{chr(start)}-{chr(end)}" for start, end in _BLOCKS)
_CJK_CHARS = frozenset("".join("".join(chr(code) for code in range(start, end + 1)) for start, end in _BLOCKS))

_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])|(?<=[A-Za-z])(?=\d)")
# What a reader would not type as a word; `[^[^\W\s]` looks equivalent but deletes CJK characters on 3.14.
_SEPARATORS = re.compile(r"[^\w\s]|_")
_CJK_RUN = re.compile(f"[{_CJK_CLASS}]+")
_SPACES = re.compile(r"\s+")


def index_text(text: str) -> str:
    """Rewrite text so every searchable unit is a separate FTS5 token."""
    if not text:
        return ""
    return _SPACES.sub(" ", _CJK_RUN.sub(lambda match: " ".join(match.group()) + " ", _bare(text))).strip()


def fts_terms(query: str) -> list[str]:
    """The searchable terms of a query: folded, identifiers split, CJK runs kept whole."""
    terms = _bare(query).split()
    if not terms:
        raise ValueError(f"search needs at least one searchable word, got {query!r}")
    return terms


def fts_expression(terms: list[str]) -> str:
    """Build the MATCH expression for terms, using the same split as the index.

    A CJK run becomes a quoted phrase so its characters stay adjacent: unphrased, a query for
    钥匙 would match text that mentions 钥 and 匙 worlds apart. Latin tokens get a prefix match,
    which is what lets `atom` reach `atoms`.

    Terms are OR-ed, not AND-ed. A question is longer than the sentence that answers it —
    "Which PRD requirements prove long context memory, HashHop, and adapters?" shares only some of
    its words with any single atom — and an AND over every word answers such a question with
    nothing. bm25 then ranks the candidates by how many of those words each one carries, so the
    broadened query does not mean a diluted answer.
    """
    if not terms:
        raise ValueError("fts_expression needs at least one term")
    return " OR ".join(_term_phrase(term) for term in terms)


def fts_all_expression(terms: list[str]) -> str:
    """Build the MATCH expression that demands every term.

    A question ORs because it is longer than the sentence that answers it. Corroboration ANDs: a
    second source either carries the claim's own words or it does not, and an OR would let one
    shared word vouch for a whole sentence.
    """
    if not terms:
        raise ValueError("fts_all_expression needs at least one term")
    return " AND ".join(_term_phrase(term) for term in terms)


def _term_phrase(term: str) -> str:
    return _cjk_phrase(term) if _is_cjk(term) else f"{_quote(term)}*"


def fts_query(query: str) -> str:
    """Build the MATCH expression for a user query, one term at a time."""
    return fts_expression(fts_terms(query))


COMMON_TERM_FRACTION = 0.05
RAREST_KEEP = 3


def rare_terms(connection: sqlite3.Connection, terms: list[str], *, fraction: float | None = None) -> list[str]:
    """Drop the terms a library uses everywhere, and keep the ones that identify an answer.

    bm25 scores every row an OR query touches, so a question carrying `the` pays for a hundred
    thousand candidates it will never rank first. Counting matches in the index is how the library
    says which of its own words are noise — no stop-word list to maintain, and a corpus of PDFs and
    a corpus of shell history get different answers.

    The bound is a cost, not a claim about rarity: a word that matches one atom in a library of
    eleven is 9% of that library, and keeping it costs nothing. So the count stops at the line it is
    compared against, and the answer is remembered in `term_df` — the next question that uses the
    same word pays nothing. Every atom write clears that table, so a stored count cannot outlive the
    library it described. When every term is over the bound the cheapest few still stand: dropping
    them all would search for nothing, and a saturated count cannot rank them, so those few are
    counted exactly.

    0.05 is measured, not chosen: on the frozen suite (n=173, holder-scoped) recall@10 peaks at
    0.899 with p50 58.6 ms there, against 0.893 / 112.9 ms at 0.20 and 0.844 / 13.4 ms at 0.01, and
    `bench/term_sweep.py` is the artifact that prints that curve. The bound is read when the call
    runs, not when the function was written, so that sweep can move it.
    """
    bound = COMMON_TERM_FRACTION if fraction is None else fraction
    if len(terms) == 1:
        return terms
    total = int(connection.execute("SELECT count(*) FROM atoms").fetchone()[0])
    if total == 0:
        return terms
    cap = max(int(total * bound) + 1, 2)
    counts = [(term, _term_matches(connection, fts_expression([term]), cap)) for term in terms]
    rare = [term for term, matches in counts if matches < cap]
    if rare:
        return rare
    exact = [(term, _exact_matches(connection, fts_expression([term]))) for term, _ in counts]
    return [term for term, _ in sorted(exact, key=lambda pair: pair[1])[:RAREST_KEEP]]


def _term_matches(connection: sqlite3.Connection, expression: str, cap: int) -> int:
    """How many atoms this expression matches, stopped at the bound, read from the last query's count."""
    row = connection.execute("SELECT documents FROM term_df WHERE term = ?", (expression,)).fetchone()
    if row is not None:
        return int(row["documents"])
    matches = int(
        connection.execute(
            "SELECT count(*) FROM (SELECT 1 FROM atom_fts WHERE atom_fts MATCH ? LIMIT ?)",
            (expression, cap),
        ).fetchone()[0]
    )
    if matches:
        # A word the corpus has never used is not remembered: a stranger's vocabulary would grow the store one row per novel question.
        connection.execute("INSERT OR REPLACE INTO term_df(term, documents) VALUES (?, ?)", (expression, matches))
    return matches


def _exact_matches(connection: sqlite3.Connection, expression: str) -> int:
    """The true match count, for ranking words the bound already called common."""
    return int(connection.execute("SELECT count(*) FROM atom_fts WHERE atom_fts MATCH ?", (expression,)).fetchone()[0])


def _bare(text: str) -> str:
    """Fold width and case, split identifiers, and drop punctuation, leaving CJK runs whole."""
    spaced = _CAMEL_BOUNDARY.sub(" ", normalize("NFKC", text))
    return _SPACES.sub(" ", _SEPARATORS.sub(" ", spaced)).strip().lower()


def _is_cjk(term: str) -> bool:
    return all(char in _CJK_CHARS for char in term)


def _phrase(run: str) -> str:
    return '"' + " ".join(run) + '"'


def _cjk_phrase(run: str) -> str:
    """A CJK run stays adjacent, and a long question also reaches the pairs inside it.

    The whole run as one phrase is the precise reading, and it is what a two-character word
    needs. A question is usually longer than the sentence that answers it: 钥匙在哪里 will not
    appear inside 我们的钥匙放在玄关抽屉里. Offering every adjacent pair as an alternative keeps
    adjacency — 钥 and 匙 still have to touch — without demanding equal length.
    """
    phrases = list(dict.fromkeys([_phrase(run)] + [_phrase(run[start : start + 2]) for start in range(len(run) - 1)]))
    return phrases[0] if len(phrases) == 1 else "(" + " OR ".join(phrases) + ")"


def _quote(term: str) -> str:
    return '"' + term.replace('"', '""') + '"'
