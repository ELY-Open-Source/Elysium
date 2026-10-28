"""CLI face for memory: write it, correct it, erase it, and walk the tiers it lives in.

Registered onto the main Typer app so the command names stay flat (`elysium remember`,
`elysium archive`) while the memory surface stays in one file. Every command answers in JSON.
"""

from __future__ import annotations

from collections.abc import Callable

import typer

from .cli_common import json_dump, moment
from .config import Settings
from .memory import MemoryService
from .schemas import MemoryOrigin, TimePrecision


def register(app: typer.Typer, settings: Callable[[], Settings]) -> None:
    """Add the memory commands. The settings thunk is passed so one patch in a test redirects
    every command, the same way the transactive and maintenance faces do."""

    def writer() -> MemoryService:
        return MemoryService(settings())

    def principal(holder: str) -> str:
        """An empty --holder means the local principal, the identity the server writes as."""
        return holder or settings().default_holder

    @app.command()
    def remember(
        text: str,
        holder: str = typer.Option("", "--holder", help="who owns this memory"),
        origin: MemoryOrigin = MemoryOrigin.self_,
        scenario: str = "",
        event_time: str = typer.Option("", "--event-time", help="when it was true, ISO with offset"),
        precision: TimePrecision = TimePrecision.unknown,
        retention_until: str = typer.Option("", "--retention-until"),
        session: str = typer.Option("", "--session", help="the session this memory belongs to"),
        importance: float = typer.Option(-1.0, "--importance", help="0..1; below 0 leaves it unset"),
    ) -> None:
        """Store one statement as a memory. Repeating it as the same holder updates it."""
        atom = writer().remember(
            text,
            holder_id=principal(holder),
            origin=origin,
            scenario=scenario,
            event_time=moment(event_time, "--event-time"),
            event_time_precision=precision,
            retention_until=moment(retention_until, "--retention-until"),
            session_id=session,
            importance=None if importance < 0 else importance,
        )
        typer.echo(atom.model_dump_json(indent=2))

    @app.command()
    def supersede(
        atom_id: str,
        text: str,
        holder: str = typer.Option("", "--holder"),
        scenario: str = "",
        event_time: str = typer.Option("", "--event-time"),
        precision: TimePrecision = TimePrecision.unknown,
        session: str = typer.Option("", "--session"),
    ) -> None:
        """Close a memory and record this one as its replacement."""
        atom = writer().supersede(
            atom_id,
            text=text,
            holder_id=principal(holder),
            scenario=scenario,
            event_time=moment(event_time, "--event-time"),
            event_time_precision=precision,
            session_id=session,
        )
        typer.echo(atom.model_dump_json(indent=2))

    @app.command()
    def forget(atom_id: str = "", source_id: str = "", reason: str = "") -> None:
        """Delete a memory and everything derived from it: vectors, cache, edges."""
        report = writer().forget(atom_id=atom_id or None, source_id=source_id or None, reason=reason)
        typer.echo(report.model_dump_json(indent=2))

    @app.command()
    def working(holder: str, session: str) -> None:
        """What one session recorded, in order, with no search involved."""
        atoms = writer().working_set(holder, session)
        typer.echo(json_dump([atom.model_dump(mode="json") for atom in atoms]))

    @app.command()
    def consolidate(scenario: str = "", holder: str = typer.Option("", "--holder")) -> None:
        """Roll a lane's new memories into its standing summary and move the watermark."""
        record = writer().consolidate(principal(holder), scenario)
        typer.echo("nothing new to roll up" if record is None else record.model_dump_json(indent=2))

    @app.command()
    def archive(
        older_than_days: int = typer.Option(90, "--older-than-days"),
        max_importance: float = typer.Option(-1.0, "--max-importance", help="archive at or under this"),
        dry_run: bool = typer.Option(False, "--dry-run", help="name the memories without moving them"),
    ) -> None:
        """Move never-used, never-valued memories out of the current tier."""
        report = writer().archive_stale(
            older_than_days=older_than_days,
            max_importance=None if max_importance < 0 else max_importance,
            dry_run=dry_run,
        )
        typer.echo(report.model_dump_json(indent=2))

    @app.command()
    def archived(holder: str = typer.Option("", "--holder")) -> None:
        """The long-term tier: what the current view is hiding."""
        atoms = writer().archived(holder or None)
        typer.echo(json_dump([atom.model_dump(mode="json") for atom in atoms]))

    @app.command("memory-restore")
    def restore(atom_ids: list[str]) -> None:
        """Bring archived memories back. Named apart from `restore`, which brings the store back."""
        typer.echo(json_dump({"restored": writer().restore(atom_ids)}))

    @app.command()
    def conflicts(holder: str = typer.Option("", "--holder")) -> None:
        """Every disagreement the store noticed and nobody has settled."""
        rows = writer().conflicts(holder or None)
        typer.echo(json_dump([row.model_dump(mode="json") for row in rows]))

    @app.command("resolve-conflicts")
    def resolve_conflicts(conflict_ids: list[int]) -> None:
        """Settle disagreements so retrieval stops choosing a side for the reader."""
        typer.echo(json_dump({"resolved": writer().resolve_conflicts(conflict_ids)}))
