"""Common words are counted over the library, but a search runs inside one holder's scope.

Measured on the frozen suite after the pictures were described: the descriptions made `axis`,
`series` and `value` common library-wide, the search dropped them, and a holder of four functions
answered "will get the axis mode for the current series" with nothing.
"""

from __future__ import annotations

from pathlib import Path

from elysium.config import Settings
from elysium.db import Database
from elysium.memory import MemoryService
from elysium.retrieval import RetrievalService
from elysium.schemas import MemoryOrigin, SearchFilters

QUESTION = "will get the axis mode for the current series"
ANSWER = "plot axis series graph"


def _library(tmp_path: Path) -> tuple[RetrievalService, str]:
    settings = Settings(home=tmp_path)
    database = Database(settings)
    memory = MemoryService(settings, database)
    for index in range(40):
        memory.remember(f"chart {index} draws an axis for each series", holder_id="charts", origin=MemoryOrigin.self_)
    answer = memory.remember(ANSWER, holder_id="flot", origin=MemoryOrigin.self_)
    return RetrievalService(settings=settings, database=database), answer.atom_id


def test_a_scope_the_rare_words_cannot_fill_is_searched_with_every_word(tmp_path: Path) -> None:
    service, answer = _library(tmp_path)

    result = service.search(QUESTION, top_k=5, filters=SearchFilters(as_holder="flot"))

    assert [hit.atom.atom_id for hit in result.hits] == [answer], "the only memory in scope shares only common words"


def test_every_page_reads_the_same_expression(tmp_path: Path) -> None:
    service, answer = _library(tmp_path)
    memory = MemoryService(service.settings, service.db)
    others = {memory.remember(f"{ANSWER} {name}", holder_id="flot", origin=MemoryOrigin.self_).atom_id for name in ("left", "right")}
    seen: list[str] = []
    cursor = None
    for _ in range(3):
        page = service.search(QUESTION, top_k=1, filters=SearchFilters(as_holder="flot"), cursor=cursor)
        seen += [hit.atom.atom_id for hit in page.hits]
        cursor = page.next_cursor

    assert sorted(seen) == sorted({answer, *others}), "a later page must not fall back to the rare words and come back empty"
