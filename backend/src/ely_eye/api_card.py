"""The capability card over HTTP: served without a token, because it is the reason to send one.

A caller deciding whether to point an agent at this store should not have to guess whether the
store holds speech, who is in the directory, or which schema answered last. Everything here is
read back from the store, so it cannot advertise a sense the store has no atoms for.

No `from __future__ import annotations` here: FastAPI reads these route signatures, and string
annotations would be resolved against module globals, where the injected settings_dep exists
only as a parameter of register().
"""

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException

from .card import build_card
from .card_schemas import CapabilityCard, HolderCard
from .config import Settings


def register(app: FastAPI, settings_dep: Callable[[], Settings]) -> None:
    """Register the card routes. Nothing here is secret: it is the store describing itself."""

    @app.get("/api/card", response_model=CapabilityCard)
    def card(settings: Annotated[Settings, Depends(settings_dep)]) -> CapabilityCard:
        return build_card(settings)

    @app.get("/api/card/{holder_id}", response_model=HolderCard)
    def holder_card(
        holder_id: str, settings: Annotated[Settings, Depends(settings_dep)]
    ) -> HolderCard:
        """One directory entry with its counted evidence; 404 names the holder that is not there."""
        for entry in build_card(settings).holders:
            if entry.holder_id == holder_id:
                return entry
        raise HTTPException(status_code=404, detail=f"no holder {holder_id!r} has memories or a directory entry")
