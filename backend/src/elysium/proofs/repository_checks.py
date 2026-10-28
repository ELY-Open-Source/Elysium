"""Find the repository the proof suite is allowed to talk about.
"""

from __future__ import annotations

import os
from pathlib import Path


def project_root() -> Path:
    current = Path.cwd().resolve()
    for candidate in (current, *current.parents):
        if (candidate / "PRD.md").exists() and (candidate / "backend" / "src" / "elysium").exists():
            return candidate
    return current


def discover_repository_files(root: Path) -> list[Path]:
    ignored_dirs = {".git", ".elysium", ".venv", ".venv-linux", "__pycache__", "node_modules", "dist", "build", "target"}
    files: list[Path] = []
    for current, dirs, names in os.walk(root):
        dirs[:] = [name for name in dirs if name not in ignored_dirs and not name.startswith(".venv")]
        current_path = Path(current)
        for name in names:
            path = current_path / name
            try:
                relative = path.relative_to(root)
            except ValueError:
                continue
            if any(part in ignored_dirs or part.startswith(".venv") for part in relative.parts):
                continue
            try:
                path.stat()
            except OSError:
                continue
            files.append(path)
    return files
