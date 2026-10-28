"""The memory tiers over HTTP: what a session holds, and what the store disagrees about.

Only the two reads an agent needs are exposed. Curation — rolling a lane up, archiving what
nobody uses, settling a disagreement — is the holder's decision, so it lives in the CLI and the
service, not in a route with no caller.

No `from __future__ import annotations` here: FastAPI reads these route signatures, and string
annotations would be resolved against module globals, where the injected settings_dep exists
only as a parameter of register().
"""

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request

from .api_auth import read_as, resolve_caller
from .config import Settings
from .db import Database
from .memory import MemoryService
from .schemas import ConflictRecord, EvidenceAtom


def register(app: FastAPI, settings_dep: Callable[[], Settings]) -> None:
    """Register the tier reads. A tier belongs to somebody, so the token decides whose it is: the
    `holder` parameter narrows the question to a name, and naming a name the token cannot back is
    refused rather than obeyed."""

    def service(settings: Settings) -> MemoryService:
        return MemoryService(settings, Database(settings))

    @app.get("/api/memory/working", response_model=list[EvidenceAtom])
    def working_set(
        session: str,
        http: Request,
        settings: Annotated[Settings, Depends(settings_dep)],
        holder: str | None = None,
    ) -> list[EvidenceAtom]:
        """What one session recorded, in the order it recorded it, with no search involved."""
        who = read_as(resolve_caller(http, settings), holder)
        if not who:
            raise HTTPException(
                status_code=422,
                detail="a working set belongs to somebody; send that holder's token, or the operator token with a holder",
            )
        try:
            return service(settings).working_set(who, session)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/memory/conflicts", response_model=list[ConflictRecord])
    def conflicts(
        http: Request,
        settings: Annotated[Settings, Depends(settings_dep)],
        holder: str | None = None,
    ) -> list[ConflictRecord]:
        """Every disagreement the store noticed and nobody has settled."""
        who = read_as(resolve_caller(http, settings), holder)
        if who == "":
            raise HTTPException(
                status_code=422,
                detail=(
                    "a disagreement belongs to somebody; send that holder's token, "
                    "or the operator token with a holder"
                ),
            )
        return service(settings).conflicts(who)
