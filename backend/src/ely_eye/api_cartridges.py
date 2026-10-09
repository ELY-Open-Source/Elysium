"""Cartridge and mount routes: a cartridge is a retrieval scope, not only an export."""

# No `from __future__ import annotations`: FastAPI resolves route annotations against this module's globals, where settings_dep exists only as a register() parameter.

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException

from .api_auth import require_write
from .cartridge import CartridgeService
from .cartridge_assets import CartridgeAssetService
from .config import Settings
from .db import Database
from .schemas import AppendRequest, CartridgeAssetReport, CartridgeManifest, MountState


def register(app: FastAPI, settings_dep: Callable[[], Settings]) -> None:
    """Mounting decides what a search may see; the KV fingerprint decides if it may mount here."""

    app.state.write_settings = settings_dep


    @app.get("/api/cartridges")
    def cartridges(settings: Annotated[Settings, Depends(settings_dep)]):
        return CartridgeService(settings).list_manifests()

    @app.get("/api/mounts", response_model=MountState)
    def mounts(settings: Annotated[Settings, Depends(settings_dep)]) -> MountState:
        return CartridgeService(settings).mount_state()

    @app.post("/api/cartridges/{cartridge_id}/mount", response_model=CartridgeManifest)
    def mount_cartridge(
        cartridge_id: str,
        settings: Annotated[Settings, Depends(settings_dep)],
        _: Annotated[None, Depends(require_write)],
    ) -> CartridgeManifest:
        try:
            return CartridgeService(settings).mount(cartridge_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/cartridges/{cartridge_id}/switch", response_model=CartridgeManifest)
    def switch_cartridge(
        cartridge_id: str,
        settings: Annotated[Settings, Depends(settings_dep)],
        _: Annotated[None, Depends(require_write)],
    ) -> CartridgeManifest:
        try:
            return CartridgeService(settings).switch(cartridge_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/cartridges/{cartridge_id}/unmount", response_model=MountState)
    def unmount_cartridge(
        cartridge_id: str,
        settings: Annotated[Settings, Depends(settings_dep)],
        _: Annotated[None, Depends(require_write)],
    ) -> MountState:
        try:
            return CartridgeService(settings).unmount(cartridge_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/cartridges/{cartridge_id}/append", response_model=CartridgeManifest)
    def append_cartridge(
        cartridge_id: str,
        request: AppendRequest,
        settings: Annotated[Settings, Depends(settings_dep)],
        _: Annotated[None, Depends(require_write)],
    ) -> CartridgeManifest:
        try:
            return CartridgeService(settings).append(cartridge_id, request.atom_ids)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/cartridges/{cartridge_id}/finalize", response_model=CartridgeAssetReport)
    def finalize_cartridge(
        cartridge_id: str,
        settings: Annotated[Settings, Depends(settings_dep)],
        _: Annotated[None, Depends(require_write)],
    ) -> CartridgeAssetReport:
        try:
            return CartridgeAssetService(settings).finalize(cartridge_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/cartridges/{cartridge_id}/refresh")
    def refresh_cartridge(
        cartridge_id: str,
        settings: Annotated[Settings, Depends(settings_dep)],
        _: Annotated[None, Depends(require_write)],
    ):
        db = Database(settings)
        try:
            return CartridgeService(settings, db).rebuild(
                cartridge_id=cartridge_id,
                atoms=db.list_atoms(),
                sources=db.list_sources(),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/cartridges/{cartridge_id}/assets", response_model=CartridgeAssetReport)
    def cartridge_assets(
        cartridge_id: str,
        settings: Annotated[Settings, Depends(settings_dep)],
    ) -> CartridgeAssetReport:
        try:
            report = CartridgeAssetService(settings).status(cartridge_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if report is None:
            raise HTTPException(status_code=404, detail="Cartridge assets have not been finalized.")
        return report
