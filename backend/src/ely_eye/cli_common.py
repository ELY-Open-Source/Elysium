"""Shared plumbing for the CLI faces, so every command answers in JSON a pipe can read."""

from __future__ import annotations

import json


def json_dump(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)
