"""The commands that keep a local store keepable: backup, restore, doctor."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import typer

from .config import Settings
from .maintenance import backup, doctor, restore


def register(app: typer.Typer, settings: Callable[[], Settings]) -> None:
    """Add the maintenance commands; the settings thunk lets one patch in a test redirect every path."""

    @app.command("backup")
    def backup_command(destination: Path, force: bool = False) -> None:
        """Copy the whole store into a folder while a running server keeps answering."""
        typer.echo(backup(settings(), destination, force).model_dump_json(indent=2))

    @app.command("restore")
    def restore_command(source: Path, force: bool = False) -> None:
        """Put a backed-up folder back; the store it replaces is kept beside the new one."""
        typer.echo(restore(settings(), source, force).model_dump_json(indent=2))

    @app.command("doctor")
    def doctor_command() -> None:
        """Report what is broken and what is only degraded; a broken store exits non-zero."""
        report = doctor(settings())
        typer.echo(report.model_dump_json(indent=2))
        if not report.ok:
            raise typer.Exit(code=1)
