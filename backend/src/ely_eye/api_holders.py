"""Holder registry, who-knows, and referral routes: the directory side of the store.

No `from __future__ import annotations` here: FastAPI reads these route signatures, and string
annotations would be resolved against module globals, where the injected settings_dep exists
only as a parameter of register().
"""

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request

from .api_auth import read_as, require_write, resolve_caller
from .config import Settings
from .db import Database
from .holder_store import HolderStore
from .schemas import utc_now
from .transactive import TransactiveService
from .transactive_schemas import (
    AskRequest,
    Holder,
    HolderUpsertRequest,
    IssuedToken,
    ReferralAnswer,
    WhoKnowsReport,
    WhoKnowsRequest,
)


def register(app: FastAPI, settings_dep: Callable[[], Settings]) -> None:
    """Register the transactive routes. The server owns the timestamps, the caller does not.

    The directory routes answer "who knows this?" and carry counts, scores and contact details but
    no memory text, so they stay readable without a token; `ask` reads the memories themselves, so
    it runs through the eyes the token proves.
    """

    app.state.write_settings = settings_dep

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
        _: Annotated[None, Depends(require_write)],
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
        _: Annotated[None, Depends(require_write)],
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

    @app.post("/api/holders/{holder_id}/token", response_model=IssuedToken)
    def issue_token(
        holder_id: str,
        settings: Annotated[Settings, Depends(settings_dep)],
        _: Annotated[None, Depends(require_write)],
    ) -> IssuedToken:
        """Mint a bearer token for one holder. Only the operator token may do this, and the value is shown once."""
        try:
            entry, token = store(settings).issue_token(holder_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        issued_at = entry.token_issued_at
        if issued_at is None:
            raise HTTPException(status_code=500, detail=f"holder {holder_id!r} holds a token but no issue time")
        return IssuedToken(holder_id=entry.holder_id, token=token, issued_at=issued_at)

    @app.delete("/api/holders/{holder_id}/token", response_model=Holder)
    def revoke_token(
        holder_id: str,
        settings: Annotated[Settings, Depends(settings_dep)],
        _: Annotated[None, Depends(require_write)],
    ) -> Holder:
        """Drop a holder's token; the holder stays in the directory, only the proof of identity goes."""
        try:
            return store(settings).revoke_token(holder_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

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
        http: Request,
        settings: Annotated[Settings, Depends(settings_dep)],
    ) -> ReferralAnswer:
        """Ask, and be referred. The memories read here belong to somebody, so the token decides whose."""
        try:
            return TransactiveService(settings).ask(
                request.question,
                as_holder=read_as(resolve_caller(http, settings), request.as_holder),
                max_hops=request.max_hops,
                include_text=request.include_text,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
