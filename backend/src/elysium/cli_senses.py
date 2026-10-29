"""The senses: what this machine can see and hear, and the commands that exercise them.

Each command here depends on a model snapshot the operator supplies. The report says which
snapshots are present so a claim about this install can be checked instead of believed.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path

import typer

from .asr import DEFERRED as SPEECH_DEFERRED
from .asr import SpeechTranscriber
from .cli_common import json_dump
from .config import Settings
from .db import Database
from .describe import DEFERRED, VisionDescriber, describe_pictures
from .vector_index import VectorIndex
from .visual_index import VisualIndex


def senses_report(settings: Settings, db: Database) -> dict[str, dict[str, object]]:
    """What this machine can see, and what it has to pretend about.

    A missing snapshot is reported, not hidden: an unrun capability is a plan, and the status
    output is where an operator learns which claims about this install are real today.
    """
    visual = VisualIndex(settings, db)
    describer = VisionDescriber(settings)
    transcriber = SpeechTranscriber(settings)
    index_present = visual.index_path.exists() and visual.map_path.exists()
    return {
        "picture_search": {
            "model_dir": str(visual.model_dir() or ""),
            "model_ready": visual.available(),
            "index": "present" if index_present else "absent",
        },
        "picture_description": {
            "base_url": describer.base_url() or "",
            "model_ready": describer.available() and describer.answers(),
            "note": "" if describer.available() else DEFERRED,
        },
        "speech": {
            "model_dir": str(transcriber.model_dir() or ""),
            "model_ready": transcriber.available(),
            "note": "" if transcriber.available() else SPEECH_DEFERRED,
        },
    }


def register(app: typer.Typer, settings: Callable[[], Settings]) -> None:
    """Add the media commands. The settings thunk lets one patch in a test redirect every command."""

    @app.command()
    def transcribe(path: Path) -> None:
        """Words with the instant each was spoken; the snapshot stays the operator's to supply."""
        segments = SpeechTranscriber(settings()).transcribe(path)
        typer.echo(json_dump([asdict(segment) for segment in segments]))

    @app.command("describe-image")
    def describe_image(path: Path) -> None:
        """Say what a picture shows; names the setup step when no vision model is installed."""
        typer.echo(json_dump({"image": str(path), "caption": VisionDescriber(settings()).describe(path)}))

    @app.command("describe-pictures")
    def describe_pictures_command(workers: int = typer.Option(32, help="requests in flight at once")) -> None:
        """Write what each stored picture shows into its text; resumes where a previous run stopped."""
        typer.echo(json_dump(describe_pictures(settings(), Database(settings()), workers)))

    @app.command("index-visual")
    def index_visual() -> None:
        """Encode every image atom so a picture or a sentence can find it."""
        database = Database(settings())
        typer.echo(json_dump(VisualIndex(settings(), database).build()))

    @app.command("build-dense-index")
    def build_dense_index() -> None:
        """Encode the memories the dense index is missing; its vectors live beside the atoms."""
        typer.echo(json_dump(VectorIndex(settings()).sync()))
