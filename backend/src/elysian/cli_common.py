"""Shared plumbing for the CLI faces, so every command answers in JSON a pipe can read."""

from __future__ import annotations

import json
from datetime import datetime


def json_dump(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def moment(value: str, option: str) -> datetime | None:
    """An ISO timestamp from the command line, with the option named in the error."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{option} {value!r} is not an ISO timestamp: {error}") from error
