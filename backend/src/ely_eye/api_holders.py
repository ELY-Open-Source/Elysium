"""Holder registry, who-knows, and referral routes: the directory side of the store.

No `from __future__ import annotations` here: FastAPI reads these route signatures, and string
annotations would be resolved against module globals, where the injected settings_dep exists
only as a parameter of register().
"""

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException

from .config import Settings
from .db import Database
from .holder_store import HolderStore
from .schemas import utc_now
from .transactive import TransactiveService
from .transactive_schemas import (
    AskRequest,
    Holder,
    HolderUpsertRequest,
    ReferralAnswer,
    WhoKnowsReport,
    WhoKnowsRequest,
)


def register(app: FastAPI, settings_dep: Callable[[], Settings]) -> None:
    """Register the transactive routes. The server owns the timestamps, the caller does not."""

    def store(settings: Settings) -> HolderStore:
        return HolderStore(Database(settings))

    @app.get("/api/holders", response_model=list[Holder])
    def holders(settings: Annotated[Settings, Depends(settings_dep)]) -> list[Holder]:
        return store(settings).list_holders()

    @app.post("/api/holders/{holder_id}", response_model=Holder)
    def put_holder(
        holder_id: str,
        request: HolderUpsertRequest,
        settings: Annotated[Settings, Depends(settings_dep)],
    ) -> Holder:
        now = utc_now()
        entry = Holder(
            holder_id=holder_id,
            created_at=now,
            updated_at=now,
            **request.model_dump(),
        )
        try:
            return store(settings).upsert(entry)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/holders/{holder_id}", response_model=Holder)
    def get_holder(
        holder_id: str,
        settings: Annotated[Settings, Depends(settings_dep)],
    ) -> Holder:
        entry = store(settings).get(holder_id)
        if entry is None:
            raise HTTPException(status_code=404, detail=f"no holder {holder_id!r} is registered")
        return entry

    @app.delete("/api/holders/{holder_id}", response_model=Holder)
    def delete_holder(
        holder_id: str,
        settings: Annotated[Settings, Depends(settings_dep)],
    ) -> Holder:
        registry = store(settings)
        entry = registry.get(holder_id)
        if entry is None:
            raise HTTPException(status_code=404, detail=f"no holder {holder_id!r} is registered")
        try:
            registry.delete(holder_id)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return entry

    @app.get("/api/holders/{holder_id}/knows", response_model=WhoKnowsReport)
    def holder_knows(
        holder_id: str,
        query: str,
        settings: Annotated[Settings, Depends(settings_dep)],
    ) -> WhoKnowsReport:
        """What this holder knows about, as a ranked directory answer."""
        try:
            return TransactiveService(settings).who_knows(query, as_holder=holder_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/who_knows", response_model=WhoKnowsReport)
    def who_knows(
        request: WhoKnowsRequest,
        settings: Annotated[Settings, Depends(settings_dep)],
    ) -> WhoKnowsReport:
        try:
            return TransactiveService(settings).who_knows(
                request.query, as_holder=request.as_holder, limit=request.limit
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/ask", response_model=ReferralAnswer)
    def ask(
        request: AskRequest,
        settings: Annotated[Settings, Depends(settings_dep)],
    ) -> ReferralAnswer:
        try:
            return TransactiveService(settings).ask(
                request.question,
                as_holder=request.as_holder,
                max_hops=request.max_hops,
                include_text=request.include_text,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
