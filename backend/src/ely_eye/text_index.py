"""One normalizer for both sides of the FTS index.

FTS5's unicode61 tokenizer splits on whitespace and punctuation only. It reads
「我们的钥匙放在玄关抽屉里」 as one token and `SearchAtoms` as one token, so a search for
钥匙 or atoms finds nothing and reports it as an empty result. Index and query must run the
same transform; keeping them in one file is what stops them from drifting apart.
"""

from __future__ import annotations

import re
from unicodedata import normalize

# Han, its extension A block, the compatibility ideographs, kana, and Hangul syllables:
# scripts written without spaces. One source of truth for both the tokenizer and the query.
_BLOCKS = ((0x3400, 0x4DBF), (0x4E00, 0x9FFF), (0xF900, 0xFAFF), (0x3040, 0x30FF), (0xAC00, 0xD7AF))
_CJK_CLASS = "".join(f"{chr(start)}-{chr(end)}" for start, end in _BLOCKS)
_CJK_CHARS = frozenset("".join("".join(chr(code) for code in range(start, end + 1)) for start, end in _BLOCKS))

_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])|(?<=[A-Za-z])(?=\d)")
# Everything a reader would not type as a word: symbols, punctuation, and the underscore
# that joins identifiers. `[^[^\W\s]` looks equivalent but deletes CJK characters on 3.14.
_SEPARATORS = re.compile(r"[^\w\s]|_")
_CJK_RUN = re.compile(f"[{_CJK_CLASS}]+")
_SPACES = re.compile(r"\s+")


def index_text(text: str) -> str:
    """Rewrite text so every searchable unit is a separate FTS5 token."""
    if not text:
        return ""
    return _SPACES.sub(" ", _CJK_RUN.sub(lambda match: " ".join(match.group()) + " ", _bare(text))).strip()


def fts_query(query: str) -> str:
    """Build the MATCH expression for a user query, using the same split as the index.

    A CJK run becomes a quoted phrase so its characters stay adjacent: unphrased, a query for
    钥匙 would match text that mentions 钥 and 匙 worlds apart. Latin tokens get a prefix match,
    which is what lets `atom` reach `atoms`.
    """
    terms = _bare(query).split()
    if not terms:
        raise ValueError(f"search needs at least one searchable word, got {query!r}")
    return " ".join(_cjk_phrase(term) if _is_cjk(term) else f"{_quote(term)}*" for term in terms)


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
