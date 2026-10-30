"""The shared leaf pieces: what a file is, and what a batch of atoms looks like."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from .schemas import EvidenceAtom, SourceRecord

SUPPORTED_TEXT_EXTENSIONS = {
    ".txt",
    ".md",
    ".json",
    ".jsonl",
    ".yaml",
    ".yml",
    ".toml",
    ".csv",
    ".html",
    ".css",
    ".xml",
}

SUPPORTED_CODE_EXTENSIONS = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".rs",
    ".go",
    ".java",
    ".cpp",
    ".c",
    ".h",
    ".hpp",
    ".cs",
    ".swift",
    ".kt",
    ".sql",
}

SUPPORTED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
SUPPORTED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}
SUPPORTED_AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".opus", ".aac", ".wma"}
REPOSITORY_INDEX_LIMIT = 5000
REPOSITORY_COMMIT_LIMIT = 50


class UnsupportedFile(ValueError):
    """No reader for this file: a walk records the reason, an explicit path fails."""


class FileTooLarge(ValueError):
    """A reader exists but the file is over the configured cap: refused with its size stated."""


@dataclass
class IngestBatch:
    sources: list[SourceRecord]
    atoms: list[EvidenceAtom]

    @property
    def token_equivalent(self) -> int:
        return sum(atom.token_equivalent for atom in self.atoms)


def image_size(path: Path) -> tuple[int, int]:
    with Image.open(path) as image:
        return image.size


def image_metadata(path: Path) -> dict[str, Any]:
    with Image.open(path) as image:
        return {"width": image.width, "height": image.height, "mode": image.mode, "format": image.format}


def file_kind(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in SUPPORTED_CODE_EXTENSIONS:
        return "code"
    if suffix in SUPPORTED_TEXT_EXTENSIONS:
        return "text"
    if suffix in SUPPORTED_IMAGE_EXTENSIONS:
        return "image"
    if suffix in SUPPORTED_VIDEO_EXTENSIONS:
        return "video"
    if suffix in SUPPORTED_AUDIO_EXTENSIONS:
        return "audio"
    if suffix == ".pdf":
        return "pdf"
    return "binary"


def relative_path(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()
