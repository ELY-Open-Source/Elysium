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

from fastapi import Depends, FastAPI, HTTPException

from .config import Settings
from .db import Database
from .memory import MemoryService
from .schemas import ConflictRecord, EvidenceAtom


def register(app: FastAPI, settings_dep: Callable[[], Settings]) -> None:
    """Register the tier reads. The holder is named by the caller because the question is about
    somebody's memory, not about the server's own identity."""

    def service(settings: Settings) -> MemoryService:
        return MemoryService(settings, Database(settings))

    @app.get("/api/memory/working", response_model=list[EvidenceAtom])
    def working_set(
        holder: str,
        session: str,
        settings: Annotated[Settings, Depends(settings_dep)],
    ) -> list[EvidenceAtom]:
        """What one session recorded, in the order it recorded it, with no search involved."""
        try:
            return service(settings).working_set(holder, session)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/memory/conflicts", response_model=list[ConflictRecord])
    def conflicts(
        settings: Annotated[Settings, Depends(settings_dep)],
        holder: str | None = None,
    ) -> list[ConflictRecord]:
        """Every disagreement the store noticed and nobody has settled."""
        return service(settings).conflicts(holder)
