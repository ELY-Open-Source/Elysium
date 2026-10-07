"""CLI face for the directory: register holders, ask who knows, ask and get referred.

Registered onto the main Typer app so the command names stay flat (`ely-eye who-knows`), while
the transactive surface stays in one file.
"""

from __future__ import annotations

from collections.abc import Callable

import typer

from .config import Settings
from .db import Database
from .holder_store import HolderStore
from .schemas import utc_now
from .transactive import TransactiveService
from .transactive_schemas import Holder, HolderKind


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
