"""Ingest anything the store can hold, and say out loud what it refused to read."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from . import trust
from .asr import SpeechTranscriber
from .config import Settings, get_settings
from .db import Database
from .describe import VisionDescriber
from .ingestion_common import (
    SUPPORTED_AUDIO_EXTENSIONS,
    SUPPORTED_CODE_EXTENSIONS,
    SUPPORTED_IMAGE_EXTENSIONS,
    SUPPORTED_TEXT_EXTENSIONS,
    SUPPORTED_VIDEO_EXTENSIONS,
    FileTooLarge,
    IngestBatch,
    UnsupportedFile,
)
from .ingestion_media import MediaIngest
from .ingestion_repository import RepositoryIngest, extract_symbols
from .schemas import (
    EvidenceAtom,
    IngestResponse,
    MemoryOrigin,
    Modality,
    SkippedFile,
    SourceRecord,
    TrustScores,
)
from .storage import (
    ObjectStore,
    guess_mime,
    safe_source_id,
    sha256_file,
    token_equivalent,
)
from .vector_index import VectorIndex


class IngestionService(MediaIngest, RepositoryIngest):
    def __init__(
        self,
        settings: Settings | None = None,
        database: Database | None = None,
        object_store: ObjectStore | None = None,
        vectors: VectorIndex | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.db = database or Database(self.settings)
        self.objects = object_store or ObjectStore(self.settings)
        self.describer = VisionDescriber(self.settings)
        self.transcriber = SpeechTranscriber(self.settings)
        self.vectors = vectors or VectorIndex(self.settings, self.db)

    def ingest_path(
        self,
        path: Path,
        cartridge_name: str | None = None,
        *,
        origin: MemoryOrigin = MemoryOrigin.artifact,
    ) -> IngestResponse:
        path = path.expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(path)
        files = self._discover_files(path)
        batch = IngestBatch(sources=[], atoms=[])
        skipped: list[SkippedFile] = []
        explicit = path.is_file()
        for file_path in files:
            try:
                file_batch = self._ingest_file(file_path)
            except (UnsupportedFile, FileTooLarge) as error:
                if explicit:
                    raise
                skipped.append(SkippedFile(path=str(file_path), reason=str(error)))
                continue
            batch.sources.extend(file_batch.sources)
            batch.atoms.extend(file_batch.atoms)
        if path.is_dir():
            repository_batch = self._ingest_repository_context(path, files)
            batch.sources.extend(repository_batch.sources)
            batch.atoms.extend(repository_batch.atoms)

        batch.atoms = keep_provenance(batch.atoms, self.db.stored_provenance([source.source_id for source in batch.sources]))
        self.db.upsert_sources(batch.sources)
        trust.stamp(batch.atoms, origin=origin)
        self.db.upsert_atoms(batch.atoms)
        self.vectors.sync_atoms([atom.atom_id for atom in batch.atoms])

        cartridge_id = None
        if cartridge_name:
            from .cartridge import CartridgeService

            cartridge = CartridgeService(self.settings, self.db).materialize(
                name=cartridge_name,
                atoms=batch.atoms,
                sources=batch.sources,
            )
            cartridge_id = cartridge.cartridge_id

        return IngestResponse(
            source_count=len(batch.sources),
            atom_count=len(batch.atoms),
            cartridge_id=cartridge_id,
            token_equivalent=batch.token_equivalent,
            sources=batch.sources,
            skipped=skipped,
        )

    def _discover_files(self, path: Path) -> list[Path]:
        if path.is_file():
            return [path]
        ignored_dirs = {".git", ".elysium", "node_modules", ".venv", ".venv-linux", "__pycache__", "dist", "build", "target"}
        files: list[Path] = []
        for root, dirs, names in os.walk(path):
            dirs[:] = [name for name in dirs if name not in ignored_dirs and not name.startswith(".venv")]
            root_path = Path(root)
            for name in names:
                child = root_path / name
                if any(part in ignored_dirs or part.startswith(".venv") for part in child.parts):
                    continue
                try:
                    if child.is_dir():
                        continue
                    child.stat()
                except OSError:
                    continue
                files.append(child)
        return files

    def _ingest_file(self, path: Path) -> IngestBatch:
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            return self._ingest_pdf(path)
        if suffix in SUPPORTED_IMAGE_EXTENSIONS:
            return self._ingest_image(path)
        if suffix in SUPPORTED_VIDEO_EXTENSIONS:
            return self._ingest_video(path)
        if suffix in SUPPORTED_AUDIO_EXTENSIONS:
            return self._ingest_audio(path)
        if suffix in SUPPORTED_CODE_EXTENSIONS:
            return self._ingest_code(path)
        if suffix in SUPPORTED_TEXT_EXTENSIONS:
            return self._ingest_text(path, Modality.text)
        raise UnsupportedFile(f"no reader for {suffix or 'a name with no extension'}")

    def _source_record(self, path: Path, kind: str, metadata: dict[str, Any] | None = None) -> SourceRecord:
        digest = sha256_file(path)
        return SourceRecord(
            source_id=safe_source_id(path, digest),
            path=str(path),
            kind=kind,
            mime=guess_mime(path),
            sha256=digest,
            size_bytes=path.stat().st_size,
            metadata=metadata or {},
        )

    def _ingest_text(self, path: Path, modality: Modality) -> IngestBatch:
        limit = self.settings.max_text_file_bytes
        size = path.stat().st_size
        if size > limit:
            raise FileTooLarge(f"{path} is {size} bytes, over max_text_file_bytes={limit}")
        source = self._source_record(path, modality.value)
        text = path.read_text(encoding="utf-8", errors="replace")
        atom = EvidenceAtom(
            atom_id=f"{source.source_id}:text",
            modality=modality,
            source_id=source.source_id,
            source=str(path),
            text=text,
            trust=TrustScores(parser=1.0, ocr=0.0, model=0.0),
            token_equivalent=token_equivalent(text),
            metadata={"extension": path.suffix.lower()},
        )
        return IngestBatch(sources=[source], atoms=[atom])

    def _ingest_code(self, path: Path) -> IngestBatch:
        batch = self._ingest_text(path, Modality.code)
        if not batch.atoms:
            return batch
        source_text = batch.atoms[0].text
        batch.atoms[0].metadata["symbols"] = extract_symbols(path, source_text)
        batch.atoms[0].metadata["line_count"] = source_text.count("\n") + 1
        return batch


# What the store already knows about a source outlives a re-read of its bytes; ingest knows none of it.
PROVENANCE = (
    "holder_id",
    "scenario",
    "visibility",
    "retention_until",
    "event_time",
    "event_time_end",
    "event_time_precision",
    "event_time_source",
)


def keep_provenance(atoms: list[EvidenceAtom], stored: dict[str, EvidenceAtom]) -> list[EvidenceAtom]:
    """Give every re-ingested atom the holder, scenario and event time its source already carries.

    Ingest stamps no holder, so without this a second read of a file someone owns writes every
    atom back as nobody's, and nobody's memory is readable by every caller. Atoms new to a known
    source, such as speech added to a video, join that source's owner instead of the public.
    """
    return [
        atom
        if atom.source_id not in stored
        else atom.model_copy(update={field: getattr(stored[atom.source_id], field) for field in PROVENANCE})
        for atom in atoms
    ]
