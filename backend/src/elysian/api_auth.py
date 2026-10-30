"""Writes need a token; a read needs one to be anybody at all.

Anything that can change stored state — a memory, an ingested source, a mounted cartridge, a
proof run — is refused unless the caller presents the token the server was started with. A
browser must also come from an allowed origin. The CLI and the MCP server reach the same
writer through the same rule, so no face of the product gets a cheaper path to the store.

A read with no token is still allowed, but it is nobody's read: it sees what nobody owns and
what is marked for everyone, and nothing else. Naming a holder is a claim about who is asking,
so it needs that holder's token or the operator token — otherwise `as_holder` would be a way to
look over anyone's shoulder by typing their name.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from fastapi import HTTPException, Request

from .db import Database
from .holder_store import HolderStore

if TYPE_CHECKING:
    from .config import Settings


@dataclass(frozen=True)
class Caller:
    """Who the server decided is asking, from the token in front of it."""

    kind: Literal["operator", "holder", "anonymous"]
    holder_id: str | None = None

    @property
    def may_name_others(self) -> bool:
        return self.kind == "operator"


def presented_token(request: Request) -> str:
    """The bearer value on this request, or an empty string when nobody presented one."""

    header = request.headers.get("authorization", "")
    return header.removeprefix("Bearer ").strip() if header.startswith("Bearer ") else ""


def resolve_caller(request: Request, settings: Settings) -> Caller:
    """Turn the bearer token into an identity. An unknown token is refused, not treated as nobody."""

    token = presented_token(request)
    if not token:
        return Caller(kind="anonymous")
    if settings.auth_token and secrets.compare_digest(token, settings.auth_token):
        return Caller(kind="operator")
    holder_id = HolderStore(Database(settings)).verify_token(token)
    if holder_id is None:
        raise HTTPException(
            status_code=401, detail="this token is neither the operator token nor a holder token"
        )
    return Caller(kind="holder", holder_id=holder_id)


def read_as(caller: Caller, claimed: str | None) -> str | None:
    """Whose eyes a read runs under. A claim the token cannot back is refused, not ignored.

    The answer is the three states the store's visibility clause understands: a holder id, the
    empty string for a caller who is nobody, and None for an operator who reads the whole library.
    """

    if claimed is None:
        return "" if caller.kind == "anonymous" else caller.holder_id
    if caller.holder_id == claimed or caller.may_name_others:
        return claimed
    if caller.holder_id is None:
        raise HTTPException(
            status_code=403,
            detail=(
                f"an anonymous caller may not read as {claimed!r}; "
                "send that holder's token or the operator token"
            ),
        )
    raise HTTPException(
        status_code=403,
        detail=(
            f"holder {caller.holder_id!r} may not read as {claimed!r}; "
            "only the operator token may name another holder"
        ),
    )


def require_write(request: Request) -> None:
    """Gate a mutating request. The app carries the settings source, so this stays a plain global."""

    settings: Settings = request.app.state.write_settings()
    origin = request.headers.get("origin")
    # The console this server serves from ELYSIAN_UI_DIR is its own origin; a forged request comes from someone else's.
    own = f"{request.url.scheme}://{request.url.netloc}"
    if origin is not None and origin not in settings.allowed_origins and origin != own:
        raise HTTPException(
            status_code=403,
            detail=f"origin {origin} may not write; allowed origins: {', '.join(settings.allowed_origins)}",
        )
    configured = settings.auth_token
    if not configured:
        raise HTTPException(
            status_code=403,
            detail="this server accepts no writes: start it with ELYSIAN_AUTH_TOKEN set",
        )
    header = request.headers.get("authorization", "")
    presented = header.removeprefix("Bearer ").strip() if header.startswith("Bearer ") else ""
    if not presented or not secrets.compare_digest(presented, configured):
        raise HTTPException(
            status_code=401,
            detail="write needs the token: send Authorization: Bearer $ELYSIAN_AUTH_TOKEN",
        )
