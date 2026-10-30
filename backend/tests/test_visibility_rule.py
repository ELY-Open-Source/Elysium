"""The visibility rule is written out in five literal statements; this test keeps them one rule.

The SQL gate refuses a concatenated statement and a view cannot take a parameter, so the clause
is copied rather than composed. A copy that drifts is invisible to every other test — the search
leg, the browse page and the picture route would each keep passing while disagreeing about who
may see a memory.
"""

from __future__ import annotations

import re
from pathlib import Path

SOURCE_DIR = Path(__file__).resolve().parents[1] / "src" / "elysian"
FILES = ("browse.py", "store_search.py", "vector_index.py")
CLAUSE = re.compile(r"\(\? IS NULL[^()]*?holder_id = ''.*?WHERE value = \?[^)]*\)\)\)\)", re.DOTALL)
EXPECTED_COPIES = 5


def _normalize(clause: str) -> str:
    """Strip what the copies are allowed to differ in: whitespace, string-literal quotes, table aliases."""

    return re.sub(r"\s+", "", clause).replace('"', "").replace("a.", "")


def test_every_copy_of_the_visibility_rule_agrees() -> None:
    found: list[tuple[str, str]] = [
        (name, _normalize(match.group(0)))
        for name in FILES
        for match in CLAUSE.finditer((SOURCE_DIR / name).read_text(encoding="utf-8"))
    ]

    assert len(found) == EXPECTED_COPIES, [name for name, _ in found]
    distinct = {clause for _, clause in found}
    assert len(distinct) == 1, [name for name, clause in found if clause != next(iter(distinct))]


def test_the_rule_still_carries_all_three_states() -> None:
    match = CLAUSE.search((SOURCE_DIR / "store_search.py").read_text(encoding="utf-8"))
    assert match is not None, "the words leg no longer carries a visibility clause"
    clause = _normalize(match.group(0))

    assert "?ISNULL" in clause, "None still reads the whole library"
    assert "holder_id=''" in clause and "$.scope')='everyone'" in clause, "unowned and public rows stay open to a stranger"
    assert "?<>''" in clause, "the empty string must stay nobody rather than matching every holder"
    assert "holder_id=?" in clause and "value=?" in clause, "the owner and the visible_to list are still checked"
