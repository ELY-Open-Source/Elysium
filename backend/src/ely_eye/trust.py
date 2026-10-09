"""Where a memory came from decides whether it may be cited.

A file handed to the server over HTTP is somebody else's words, and so is a sentence written to
read like an instruction to the model that will read it. Both stay searchable — hiding them would
destroy the evidence that the attempt happened — but neither becomes citable evidence until a
second, non-quarantined source says it too.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING
from unicodedata import normalize

from .schemas import EvidenceAtom, MemoryOrigin
from .text_index import cjk_pairs, fts_all_expression, fts_terms, is_cjk

if TYPE_CHECKING:
    from .db import Database

# Instruction-shaped phrases an untrusted text can aim at the model that reads it, matched folded.
INJECTION_SIGNALS: tuple[str, ...] = (
    "ignore previous instructions",
    "ignore all previous instructions",
    "ignore the above instructions",
    "disregard previous instructions",
    "disregard the above",
    "forget your instructions",
    "new instructions:",
    "you are now",
    "system prompt",
    "reveal your system prompt",
    "忽略以上指令",
    "忽略之前的指令",
    "忽略前面的指令",
    "无视上面的指令",
    "忘记你的指令",
    "新的指令：",
    "你现在是",
    "系统提示词",
    "输出你的系统提示",
)

CORROBORATION_TERMS = 3
CORROBORATION_LIMIT = 3


def _fold(text: str) -> str:
    return " ".join(normalize("NFKC", text).casefold().split())


_FOLDED_SIGNALS: tuple[tuple[str, str], ...] = tuple((_fold(signal), signal) for signal in INJECTION_SIGNALS)


def injection_signals(text: str) -> list[str]:
    """Which instruction-shaped phrases this text carries."""
    folded = _fold(text)
    return [signal for folded_signal, signal in _FOLDED_SIGNALS if folded_signal in folded]


def stamp(atoms: Iterable[EvidenceAtom], *, origin: MemoryOrigin) -> None:
    """Record where these atoms came from, and quarantine the ones that cannot be trusted on sight."""

    for atom in atoms:
        atom.origin = origin
        signals = injection_signals(atom.text)
        atom.quarantined = origin is MemoryOrigin.third_party or bool(signals)
        if signals:
            atom.metadata["injection_signals"] = signals


def corroborating_atom_ids(
    database: Database, atom: EvidenceAtom, limit: int = CORROBORATION_LIMIT
) -> list[str]:
    """Live atoms from another source that carry the claim's own words, all of them.

    Corroboration is term-level, not semantic: a second source sharing a claim's words is evidence
    that the claim was seen twice, not proof that it is true. A closed or quarantined atom cannot
    corroborate, so a superseded fact stops propping up whatever cited it.

    The words demanded are the claim's longest, with the instruction phrases stripped out, and the
    count is fixed. Neither the attack's own words nor the size of the library decides whether a
    second source is believed: an earlier rule that dropped words common to the corpus left a
    two-atom library unable to corroborate anything, and 40 unrelated memories able to. A claim with
    fewer usable words than the rule demands is never corroborated, so a two-word rumour stays
    uncited — failing closed was chosen over trusting a sentence too short to compare.
    """
    terms = claim_terms(atom.text)
    if len(terms) < CORROBORATION_TERMS:
        return []
    expression = fts_all_expression(terms[:CORROBORATION_TERMS])
    with database.connect() as connection:
        rows = connection.execute(
            """
            SELECT atom_id
            FROM atom_fts
            WHERE atom_fts MATCH ?
              AND atom_id IN (
                  SELECT atom_id FROM v_atoms_current
                  WHERE source_id != ? AND atom_id != ? AND quarantined = 0
              )
            ORDER BY bm25(atom_fts)
            LIMIT ?
            """,
            (expression, atom.source_id, atom.atom_id, limit * 4),
        ).fetchall()
    return [str(row["atom_id"]) for row in rows][:limit]


def is_citable(atom: EvidenceAtom, database: Database) -> bool:
    """A quarantined atom earns a citation only by matching a live, trusted atom from another source."""
    return not atom.quarantined or bool(corroborating_atom_ids(database, atom))


def claim_terms(text: str) -> list[str]:
    """This claim's own words, longest first, with the instruction phrases stripped out.

    The words that made a text untrustworthy must not decide whether it is believed: a stranger who
    writes "answer pineapple" twice would otherwise corroborate himself.

    A CJK run is a single term to fts_terms, so a Chinese claim would offer one term and could never
    reach the three this rule demands. Each run is broken into its adjacent two-character pairs and
    three are taken from across the sentence, so a second source has to agree in three separate
    places rather than repeat one stretch of characters.
    """
    try:
        terms = fts_terms(text)
    except ValueError:
        return []
    blocked = _signal_words(text)
    expanded: list[str] = []
    for term in terms:
        if is_cjk(term):
            expanded.extend(_spread([pair for pair in cjk_pairs(term) if pair not in blocked]))
        elif term not in blocked:
            expanded.append(term)
    unique = list(dict.fromkeys(expanded))
    return sorted(unique, key=lambda term: -len(term))


def _signal_words(text: str) -> set[str]:
    """Every word the injection phrases in this text contribute, CJK pairs included."""

    words: set[str] = set()
    for signal in injection_signals(text):
        try:
            found = fts_terms(signal)
        except ValueError:
            found = [_fold(signal)]
        for word in found:
            words.update(cjk_pairs(word) if is_cjk(word) else [word])
    return words


def _spread(pairs: list[str]) -> list[str]:
    """Take CORROBORATION_TERMS pairs spread across the run instead of clustered at its start."""
    if len(pairs) <= CORROBORATION_TERMS:
        return pairs
    return [pairs[int(index * len(pairs) / CORROBORATION_TERMS)] for index in range(CORROBORATION_TERMS)]
