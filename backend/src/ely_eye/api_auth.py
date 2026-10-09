"""Writes need a token; queries do not.

Anything that can change stored state — a memory, an ingested source, a mounted cartridge, a
proof run — is refused unless the caller presents the token the server was started with. A
browser must also come from an allowed origin. The CLI and the MCP server reach the same
writer through the same rule, so no face of the product gets a cheaper path to the store.
"""

from __future__ import annotations

import secrets
from typing import TYPE_CHECKING

from fastapi import HTTPException, Request

if TYPE_CHECKING:
    from .config import Settings


def require_write(request: Request) -> None:
    """Gate a mutating request. The app carries the settings source, so this stays a plain global."""

    settings: Settings = request.app.state.write_settings()
    origin = request.headers.get("origin")
    if origin is not None and origin not in settings.allowed_origins:
        raise HTTPException(
            status_code=403,
            detail=f"origin {origin} may not write; allowed origins: {', '.join(settings.allowed_origins)}",
        )
    configured = settings.auth_token
    if not configured:
        raise HTTPException(
            status_code=403,
            detail="this server accepts no writes: start it with ELY_EYE_AUTH_TOKEN set",
        )
    header = request.headers.get("authorization", "")
    presented = header.removeprefix("Bearer ").strip() if header.startswith("Bearer ") else ""
    if not presented or not secrets.compare_digest(presented, configured):
        raise HTTPException(
            status_code=401,
            detail="write needs the token: send Authorization: Bearer $ELY_EYE_AUTH_TOKEN",
        )
