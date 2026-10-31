"""The commands that make a local store and keep it keepable: init, backup, restore, doctor."""

from __future__ import annotations

import json
import os
import secrets
from collections.abc import Callable
from pathlib import Path

import typer

from .config import Settings
from .db import Database
from .maintenance import backup, doctor, restore


def init(settings: Settings) -> dict[str, object]:
    """Make the store and, once, an operator token only this user can read; the token is never printed."""
    settings.ensure_dirs()
    Database(settings).init()
    created = not settings.token_file.exists()
    if created:
        descriptor = os.open(settings.token_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as token:
            token.write(secrets.token_urlsafe(32) + "\n")
    return {"home": str(settings.home), "database": str(settings.db_path), "token_file": str(settings.token_file), "token_created": created}


def register(app: typer.Typer, settings: Callable[[], Settings]) -> None:
    """Add the maintenance commands; the settings thunk lets one patch in a test redirect every path."""

    @app.command("init")
    def init_command() -> None:
        """Make the store and the operator token the API and the MCP server read."""
        typer.echo(json.dumps(init(settings()), indent=2))

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
