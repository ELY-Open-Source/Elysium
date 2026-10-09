"""Models for the directory side of memory: who exists, who knows what, and who answered.

Confidence here is ordinal, not calibrated: it orders candidates by the evidence in front of
us. Every model that carries a score also carries the raw evidence behind it, so a caller can
disagree with the number without re-running the query.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

HolderKind = Literal["person", "agent", "service"]
"""The registry's own vocabulary; migrations.py enforces the same set in the database."""


class Holder(BaseModel):
    """A registered person, agent, or service that can hold or answer memories."""

    holder_id: str
    name: str = ""
    kind: HolderKind = "person"
    knows_about: list[str] = Field(default_factory=list)
    contact: dict[str, str] = Field(default_factory=dict)
    token_issued_at: datetime | None = None
    """When a bearer token was last issued here. The hash itself stays out of the answer."""
    created_at: datetime
    updated_at: datetime

    @field_validator("holder_id")
    @classmethod
    def _holder_id_is_usable(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("holder_id cannot be blank; a directory entry has to name somebody")
        return value.strip()


class IssuedToken(BaseModel):
    """A holder's bearer token, shown once at the moment it is minted.

    Only the hash is stored, so this answer is the only place the value will ever appear: a lost
    token is replaced, not recovered.
    """

    holder_id: str
    token: str
    issued_at: datetime


class HolderUpsertRequest(BaseModel):
    """What a caller may set about a holder. The id comes from the path, never the body."""

    name: str = ""
    kind: HolderKind = "person"
    knows_about: list[str] = Field(default_factory=list)
    contact: dict[str, str] = Field(default_factory=dict)


class WhoKnowsHit(BaseModel):
    """One candidate holder, the evidence for them, and how to reach them."""

    holder_id: str
    name: str = ""
    confidence: float
    matched: int
    top_score: float
    latest_time: datetime | None = None
    basis: list[str] = Field(default_factory=list)
    contact: dict[str, str] = Field(default_factory=dict)


class WhoKnowsReport(BaseModel):
    """The directory's answer to a question. `no_holder_knows` is a result, not a failure."""

    query: str
    as_holder: str | None = None
    status: Literal["found", "no_holder_knows"]
    hits: list[WhoKnowsHit] = Field(default_factory=list)


class WhoKnowsRequest(BaseModel):
    """Ask the directory who holds an answer."""

    query: str
    as_holder: str | None = None
    limit: int = Field(default=8, gt=0)

    @field_validator("query")
    @classmethod
    def _query_is_usable(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("who_knows needs a query")
        return value.strip()


class AskRequest(BaseModel):
    """Ask a question on behalf of one holder, allowing a bounded chain of referrals."""

    question: str
    as_holder: str | None = None
    max_hops: int = 3
    include_text: bool = False

    @field_validator("question")
    @classmethod
    def _question_is_usable(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("ask needs a question")
        return value.strip()


class ReferralAnswer(BaseModel):
    """Who answered, who was asked along the way, and what may be shown.

    `referred` means the directory found someone who knows but the asker may not read their
    memory: the answer is the pointer and the contact, never the text.
    """

    question: str
    as_holder: str | None = None
    status: Literal["answered", "referred", "no_holder_knows"]
    answered_by: str | None = None
    asked: list[str] = Field(default_factory=list)
    hops: int = 0
    atom_ids: list[str] = Field(default_factory=list)
    answer: str | None = None
    basis: list[str] = Field(default_factory=list)
