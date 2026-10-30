"""The capability card: what this store can answer, stated as data.

Held apart from the memory schemas because the card is a promise made to a stranger — it is served
without a token — while the memory schemas describe what a holder's own memories look like. The
two change for different reasons, so they live in different files.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from .schemas import MountState, utc_now
from .transactive_schemas import HolderKind


class HolderCard(BaseModel):
    """One directory entry, plus the evidence that it is a holder rather than a typed-in name.

    `memories` and `newest_memory` are counted from the store, so a holder who declared ten
    topics and recorded nothing shows as such. `token_issued` says whether anything can prove it
    is this holder; `registered` says whether the directory knows it at all, which is false for a
    holder_id that only ever appeared on a memory.
    """

    holder_id: str
    name: str = ""
    kind: HolderKind = "person"
    knows_about: list[str] = Field(default_factory=list)
    contact: dict[str, str] = Field(default_factory=dict)
    memories: int = Field(ge=0, default=0)
    modalities: dict[str, int] = Field(default_factory=dict)
    scenarios: list[str] = Field(default_factory=list)
    newest_memory: datetime | None = None
    registered: bool = False
    token_issued: bool = False


class CapabilityCard(BaseModel):
    """What a caller can expect from this store before it sends anything into it.

    `has_audio` exists because a store that ingested only pictures and PDFs answers questions
    about speech with OCR of a frame, and the caller should learn that before it relies on it.
    `schema_version` is read from the open database, not from the build constant, so a store that
    has not been migrated yet reports what it actually is. The card is served without a token: it
    names holders, counts their memories and lists the scenario names they used, but no memory
    text — a caller learns what this store can answer, not what it remembers.
    """

    schema_version: int
    atoms: int = Field(ge=0)
    sources: int = Field(ge=0)
    modalities: dict[str, int] = Field(default_factory=dict)
    has_audio: bool
    holders: list[HolderCard] = Field(default_factory=list)
    mounts: MountState
    generated_at: datetime = Field(default_factory=utc_now)
