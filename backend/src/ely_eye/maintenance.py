"""Move the store and ask whether it is well: backup, restore, doctor."""

from __future__ import annotations

import hashlib
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel

from . import __version__
from .cartridge_store import mounted_ids
from .config import Settings
from .db import Database
from .migrations import SCHEMA_VERSION
from .schemas import utc_now
from .senses import sense_facts
from .status_schemas import SenseStatus

BACKUP_FILE = "ely_eye.sqlite"
MANIFEST_FILE = "backup_manifest.json"
_REQUIRED_TABLES = ("atoms", "sources", "cartridges")


class BackupManifest(BaseModel):
    """What a backup holds, so a folder of files can be checked before it is trusted."""

    created_at: datetime
    ely_eye_version: str
    schema_version: int
    atoms: int
    sources: int
    cartridges: int
    sha256: str
    size_bytes: int
    path: str


class DoctorReport(BaseModel):
    """Broken versus degraded: problems stop the store, warnings only shrink what it can do."""

    ok: bool
    store: str
    schema_version: int | None = None
    atoms: int = 0
    sources: int = 0
    cartridges: int = 0
    mounted: list[str] = []
    problems: list[str] = []
    warnings: list[str] = []


def _atoms_word(count: int) -> str:
    return "atom" if count == 1 else "atoms"


def _counts(connection: sqlite3.Connection) -> dict[str, int]:
    return {
        "atoms": int(connection.execute("SELECT COUNT(*) FROM atoms").fetchone()[0]),
        "sources": int(connection.execute("SELECT COUNT(*) FROM sources").fetchone()[0]),
        "cartridges": int(connection.execute("SELECT COUNT(*) FROM cartridges").fetchone()[0]),
    }


def _schema_version(connection: sqlite3.Connection) -> int:
    return int(connection.execute("PRAGMA user_version").fetchone()[0])


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def backup(settings: Settings, destination: Path, force: bool = False) -> BackupManifest:
    """Copy the live store with SQLite's own backup API, so a running server still yields a whole file."""
    origin = settings.db_path
    if not origin.exists():
        raise ValueError(f"no memory store at {origin}; nothing to back up")
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / BACKUP_FILE
    if target.exists() and not force:
        raise ValueError(f"{target} already holds a backup; pass --force to replace it")
    with sqlite3.connect(origin) as source, sqlite3.connect(target) as copy:
        source.backup(copy)
        counted = _counts(copy)
        version = _schema_version(copy)
    manifest = BackupManifest(
        created_at=utc_now(),
        ely_eye_version=__version__,
        schema_version=version,
        atoms=counted["atoms"],
        sources=counted["sources"],
        cartridges=counted["cartridges"],
        sha256=_sha256(target),
        size_bytes=target.stat().st_size,
        path=str(target),
    )
    (destination / MANIFEST_FILE).write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    return manifest


def _read_sidecar(source: Path) -> tuple[BackupManifest, int]:
    manifest_path = source / MANIFEST_FILE
    backup_file = source / BACKUP_FILE
    if not manifest_path.is_file() or not backup_file.is_file():
        raise ValueError(f"{source} is not a backup: it needs {BACKUP_FILE} and {MANIFEST_FILE} inside it")
    manifest = BackupManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    digest = _sha256(backup_file)
    if digest != manifest.sha256:
        raise ValueError(
            f"{backup_file} does not match its manifest: the file hashes {digest[:12]}, the manifest says {manifest.sha256[:12]}"
        )
    with sqlite3.connect(backup_file) as connection:
        if str(connection.execute("PRAGMA integrity_check").fetchone()[0]) != "ok":
            raise ValueError(f"{backup_file} fails integrity_check; do not restore it")
        tables = {
            str(row[0])
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        }
        missing = [table for table in _REQUIRED_TABLES if table not in tables]
        if missing:
            raise ValueError(f"{backup_file} is missing the tables this store needs: {', '.join(missing)}")
        version = _schema_version(connection)
    return manifest, version


def restore(settings: Settings, source: Path, force: bool = False) -> BackupManifest:
    """Put a backup back, and keep the store it replaces out of reach instead of under it."""
    manifest, version = _read_sidecar(source)
    if version > SCHEMA_VERSION:
        raise ValueError(
            f"{source / BACKUP_FILE} was written by a newer build: schema {version}, this build understands {SCHEMA_VERSION}"
        )
    live = settings.db_path
    if live.exists():
        if not force:
            raise ValueError(f"{live} already holds a store; pass --force to replace it")
        kept = live.with_suffix(".before-restore")
        try:
            shutil.move(str(live), kept)
            for suffix in ("-wal", "-shm"):
                sibling = Path(f"{live}{suffix}")
                if sibling.exists():
                    shutil.move(str(sibling), Path(f"{kept}{suffix}"))
        except OSError as error:
            raise ValueError(f"cannot move {live} aside to {kept}: {error}") from error
    live.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copyfile(source / BACKUP_FILE, live)
    except OSError as error:
        raise ValueError(f"cannot write the store to {live}: {error}") from error
    Database(settings).init()
    return manifest.model_copy(update={"path": str(live)})


def _check_cartridges(database: Database, mounted: list[str], problems: list[str]) -> None:
    roots = {str(row["cartridge_id"]): str(row["root_path"]) for row in database.list_cartridges()}
    for cartridge_id in mounted:
        root = roots.get(cartridge_id)
        if root is None:
            problems.append(f"{cartridge_id} is mounted but no cartridge row names it")
        elif not Path(root).exists():
            problems.append(f"{cartridge_id} is mounted but its files at {root} are gone")


def _check_senses(facts: SenseStatus, warnings: list[str]) -> None:
    """Render the missing senses as sentences; the counting lives in senses.py, not here."""
    encodable = facts.picture_atoms - facts.picture_bytes_missing
    if facts.clip_path is not None and facts.visual == "absent":
        warnings.append(f"the CLIP snapshot at {facts.clip_path} is missing, so wordless pictures cannot be found")
    elif encodable and facts.visual == "absent":
        warnings.append(
            f"the store holds {encodable} picture {_atoms_word(encodable)} but no CLIP snapshot is set "
            "(ELY_EYE_CLIP_MODEL_DIR), so they are findable only by the text already on them"
        )
    elif facts.visual == "stale":
        warnings.append("the visual index is behind the store; run `ely-eye index-visual`")
    if facts.picture_bytes_missing:
        missing = facts.picture_bytes_missing
        warnings.append(
            f"{missing} picture {_atoms_word(missing)} with no bytes behind them; re-ingest the source they came from"
        )
    if facts.asr_path is not None and facts.speech == "missing":
        warnings.append(f"the speech snapshot at {facts.asr_path} is missing, so audio cannot be transcribed")
    elif facts.audio_atoms and facts.speech == "absent":
        warnings.append(
            f"the store holds {facts.audio_atoms} audio {_atoms_word(facts.audio_atoms)} but no speech snapshot is set "
            "(ELY_EYE_ASR_MODEL_DIR), so new audio will not be transcribed"
        )
    if facts.vlm_path is not None and facts.captioning == "missing":
        warnings.append(f"the captioning model at {facts.vlm_path} is missing, so images stay uncaptioned")


def _check_indexes(facts: SenseStatus, warnings: list[str]) -> None:
    if facts.dense == "missing":
        warnings.append("dense embeddings are on but no index exists; run `ely-eye build-dense-index`")
    elif facts.dense == "behind":
        warnings.append(
            f"the dense index holds {facts.dense_covered} of the {facts.dense_expected} memories with words; "
            "run `ely-eye build-dense-index`"
        )


def doctor(settings: Settings) -> DoctorReport:
    """Say what is broken and what is only degraded, and name the command that fixes each."""
    problems: list[str] = []
    warnings: list[str] = []
    live = settings.db_path
    if not live.exists():
        return DoctorReport(
            ok=False,
            store=str(live),
            schema_version=None,
            problems=[f"no memory store at {live}; run `ely-eye ingest` or `ely-eye remember` first"],
        )
    database: Database
    try:
        database = Database(settings)
    except SystemExit as error:
        return DoctorReport(
            ok=False,
            store=str(live),
            problems=[f"the store cannot be opened by this build: {error}"],
        )
    with database.connect() as connection:
        if str(connection.execute("PRAGMA integrity_check").fetchone()[0]) != "ok":
            problems.append(f"{live} fails integrity_check; restore a backup before writing to it")
        version = _schema_version(connection)
    if version != SCHEMA_VERSION:
        problems.append(f"the schema settled at version {version} while this build writes {SCHEMA_VERSION}")
    mounted = mounted_ids(database)
    _check_cartridges(database, mounted, problems)
    facts = sense_facts(settings, database)
    _check_senses(facts, warnings)
    _check_indexes(facts, warnings)
    if settings.ui_dir is not None and not settings.ui_dir.exists():
        problems.append(f"ui_dir {settings.ui_dir} is set but holds no built interface, so the API refuses to start")
    return DoctorReport(
        ok=not problems,
        store=str(live),
        schema_version=version,
        atoms=database.atom_count(),
        sources=database.source_count(),
        cartridges=database.cartridge_count(),
        mounted=mounted,
        problems=problems,
        warnings=warnings,
    )
