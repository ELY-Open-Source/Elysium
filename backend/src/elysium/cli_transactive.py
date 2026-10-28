"""CLI face for the directory: register holders, ask who knows, ask and get referred.

Registered onto the main Typer app so the command names stay flat (`elysium who-knows`), while
the transactive surface stays in one file.
"""

from __future__ import annotations

from collections.abc import Callable

import typer

from .card import build_card
from .config import Settings
from .db import Database
from .holder_store import HolderStore
from .schemas import utc_now
from .transactive import TransactiveService
from .transactive_schemas import Holder, HolderKind, IssuedToken


def register(app: typer.Typer, settings: Callable[[], Settings]) -> None:
    """Add the holder and referral commands. The caller passes a settings thunk so one patch
    in a test redirects every command, the same way the cartridge routes do."""

    def store() -> HolderStore:
        return HolderStore(Database(settings()))

    def asker(as_holder: str) -> str:
        """An empty --as-holder means the local principal, the same identity `remember` writes as."""
        return as_holder or settings().default_holder

    @app.command("holders")
    def holders() -> None:
        """List registered holders: the directory a referral walks."""
        for entry in store().list_holders():
            typer.echo(entry.model_dump_json(indent=2))

    @app.command("holder-set")
    def holder_set(
        holder_id: str,
        name: str = "",
        kind: HolderKind = "person",
        knows_about: list[str] = typer.Option(None, "--knows-about"),
        contact: list[str] = typer.Option(None, "--contact", help="key=value, repeatable"),
    ) -> None:
        """Create or replace one holder entry."""
        now = utc_now()
        entry = Holder(
            holder_id=holder_id,
            name=name,
            kind=kind,
            knows_about=list(knows_about or []),
            contact=_pairs(contact),
            created_at=now,
            updated_at=now,
        )
        typer.echo(store().upsert(entry).model_dump_json(indent=2))

    @app.command("holder-rm")
    def holder_rm(holder_id: str) -> None:
        """Delete a holder. Refuses while that holder still owns memories."""
        store().delete(holder_id)
        typer.echo(f'{{"deleted": "{holder_id}"}}')

    @app.command("holder-issue")
    def holder_issue(holder_id: str) -> None:
        """Mint a bearer token for one holder. The value appears once: only its hash is stored."""
        entry, token = store().issue_token(holder_id)
        if entry.token_issued_at is None:
            raise ValueError(f"holder {holder_id!r} holds a token but no issue time")
        issued = IssuedToken(holder_id=entry.holder_id, token=token, issued_at=entry.token_issued_at)
        typer.echo(issued.model_dump_json(indent=2))

    @app.command("holder-revoke")
    def holder_revoke(holder_id: str) -> None:
        """Drop a holder's token. The entry stays; nobody can read as them until a new one is issued."""
        typer.echo(store().revoke_token(holder_id).model_dump_json(indent=2))

    @app.command()
    def card() -> None:
        """What this store can answer, read back from what it holds: holders, senses, schema, mounts."""
        typer.echo(build_card(settings()).model_dump_json(indent=2))

    @app.command("who-knows")
    def who_knows(query: str, as_holder: str = "", limit: int = 8) -> None:
        """Rank the holders whose memories answer this query."""
        report = TransactiveService(settings()).who_knows(
            query, as_holder=asker(as_holder), limit=limit
        )
        typer.echo(report.model_dump_json(indent=2))

    @app.command()
    def ask(
        question: str,
        as_holder: str = "",
        max_hops: int = 3,
        include_text: bool = typer.Option(
            False, "--include-text", help="show the memory text when the asker may already read it"
        ),
    ) -> None:
        """Ask the store, then whoever knows. An unanswered question says nobody knows."""
        answer = TransactiveService(settings()).ask(
            question,
            as_holder=asker(as_holder),
            max_hops=max_hops,
            include_text=include_text,
        )
        typer.echo(answer.model_dump_json(indent=2))


def _pairs(values: list[str] | None) -> dict[str, str]:
    """Turn repeatable key=value options into a contact map, naming any entry that is not one."""
    contact: dict[str, str] = {}
    for value in values or []:
        key, separator, detail = value.partition("=")
        if not separator or not key.strip():
            raise ValueError(f"--contact needs key=value, got {value!r}")
        contact[key.strip()] = detail
    return contact
