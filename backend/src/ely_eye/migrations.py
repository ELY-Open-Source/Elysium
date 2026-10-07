"""Schema DDL and versioned migrations for the memory store.

A memory row must answer four questions before retrieval can trust it: whose memory
is it, where did it come from, when was it true, and in what situation may it be used.
The first version of this table answered none of them, so every consumer guessed.

Versioning uses PRAGMA user_version. A database written by the first version is
upgraded in place rather than rebuilt, because the only copy of the memory is the file.
"""

from __future__ import annotations

import sqlite3

from .text_index import index_text

SCHEMA_VERSION = 6

ATOM_COLUMNS_V2 = """
    atom_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES sources(source_id) ON DELETE CASCADE,
    modality TEXT NOT NULL,
    source TEXT NOT NULL,
    ingested_at TEXT NOT NULL,
    text TEXT NOT NULL,
    image_ref TEXT,
    embedding_refs_json TEXT NOT NULL,
    layout_json TEXT,
    relations_json TEXT NOT NULL,
    trust_json TEXT NOT NULL,
    token_equivalent INTEGER NOT NULL,
    metadata_json TEXT NOT NULL,
    holder_id TEXT NOT NULL DEFAULT '',
    origin TEXT NOT NULL DEFAULT 'artifact'
        CHECK (origin IN ('self', 'observed', 'artifact', 'third_party')),
    scenario TEXT NOT NULL DEFAULT '',
    event_time TEXT,
    event_time_end TEXT,
    event_time_precision TEXT NOT NULL DEFAULT 'unknown'
        CHECK (event_time_precision IN ('instant', 'minute', 'hour', 'day', 'month', 'year', 'unknown')),
    event_time_source TEXT NOT NULL DEFAULT '',
    valid_from TEXT,
    valid_to TEXT,
    supersedes_json TEXT NOT NULL DEFAULT '[]',
    visibility_json TEXT NOT NULL DEFAULT '{}',
    retention_until TEXT
"""

_BASE_TABLES = """
    CREATE TABLE IF NOT EXISTS sources (
        source_id TEXT PRIMARY KEY,
        path TEXT NOT NULL,
        kind TEXT NOT NULL,
        mime TEXT NOT NULL,
        sha256 TEXT NOT NULL,
        size_bytes INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        metadata_json TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS cartridges (
        cartridge_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        root_path TEXT NOT NULL,
        manifest_json TEXT NOT NULL,
        dna TEXT,
        token_equivalent INTEGER NOT NULL,
        created_at TEXT NOT NULL
    );

    -- Membership lives in the live store, not only in the copied parquet, otherwise
    -- "mount this cartridge" cannot scope a query against the atoms it holds.
    CREATE TABLE IF NOT EXISTS cartridge_atoms (
        cartridge_id TEXT NOT NULL REFERENCES cartridges(cartridge_id) ON DELETE CASCADE,
        atom_id TEXT NOT NULL REFERENCES atoms(atom_id) ON DELETE CASCADE,
        added_at TEXT NOT NULL,
        PRIMARY KEY (cartridge_id, atom_id)
    );

    CREATE TABLE IF NOT EXISTS mounts (
        cartridge_id TEXT PRIMARY KEY REFERENCES cartridges(cartridge_id) ON DELETE CASCADE,
        mounted_at TEXT NOT NULL
    );

    -- The directory of who may hold or answer a memory. A transactive system answers
    -- "who knows this?" before it answers "what is this?", and it cannot do that without
    -- an entity to point at. Contact details are free-form on purpose: the transport is
    -- whoever wired this store together, not the schema.
    CREATE TABLE IF NOT EXISTS holders (
        holder_id TEXT PRIMARY KEY,
        name TEXT NOT NULL DEFAULT '',
        kind TEXT NOT NULL DEFAULT 'person'
            CHECK (kind IN ('person', 'agent', 'service')),
        knows_about_json TEXT NOT NULL DEFAULT '[]',
        contact_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS cache_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT NOT NULL,
        layer TEXT NOT NULL,
        cache_key TEXT NOT NULL,
        event TEXT NOT NULL,
        bytes_estimate INTEGER NOT NULL,
        metadata_json TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS evidence_edges (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        from_atom_id TEXT NOT NULL,
        to_atom_id TEXT NOT NULL,
        relation TEXT NOT NULL,
        confidence REAL NOT NULL,
        metadata_json TEXT NOT NULL
    );

    -- How many atoms one query expression matches, remembered so the next question does not
    -- count the same rows again. Every atom write clears it, so a count is never read stale.
    CREATE TABLE IF NOT EXISTS term_df (
        term TEXT PRIMARY KEY,
        documents INTEGER NOT NULL
    );

CREATE VIRTUAL TABLE IF NOT EXISTS atom_fts USING fts5(
atom_id UNINDEXED,
source,
text,
tokenize = 'unicode61'
);
-- source and text hold text_index output, not the atom's own text: unicode61 sees one token
-- per CJK character and per identifier fragment, which is what makes those queries match.
"""

# A memory is usable now when nothing has closed it, it had begun by now, and its
# retention has not lapsed. Unknown bounds read as visible: absence of evidence about
# when a legacy row was true is not evidence that it is false. The clock is formatted to
# match how Python writes an aware datetime, so the comparison is exact to the millisecond.
VIEWS = """
    CREATE VIEW IF NOT EXISTS v_atoms_current AS
    SELECT * FROM atoms
    WHERE valid_to IS NULL
      AND (valid_from IS NULL OR valid_from <= strftime('%Y-%m-%dT%H:%M:%f+00:00', 'now'))
      AND (retention_until IS NULL OR retention_until >= strftime('%Y-%m-%dT%H:%M:%f+00:00', 'now'));

    CREATE INDEX IF NOT EXISTS idx_atoms_source_id ON atoms(source_id);
    CREATE INDEX IF NOT EXISTS idx_atoms_modality ON atoms(modality);
    CREATE INDEX IF NOT EXISTS idx_atoms_holder ON atoms(holder_id);
    CREATE INDEX IF NOT EXISTS idx_atoms_scenario ON atoms(scenario);
    CREATE INDEX IF NOT EXISTS idx_atoms_valid_to ON atoms(valid_to);
"""

# Columns the first version lacked, in the order they are added. Every one is nullable
# or has a default, so an existing row survives the upgrade with its meaning intact.
_V1_TO_V2_COLUMNS = (
    ("holder_id", "TEXT NOT NULL DEFAULT ''"),
    ("origin", "TEXT NOT NULL DEFAULT 'artifact'"),
    ("scenario", "TEXT NOT NULL DEFAULT ''"),
    ("event_time", "TEXT"),
    ("event_time_end", "TEXT"),
    ("event_time_precision", "TEXT NOT NULL DEFAULT 'unknown'"),
    ("event_time_source", "TEXT NOT NULL DEFAULT ''"),
    ("valid_from", "TEXT"),
    ("valid_to", "TEXT"),
    ("supersedes_json", "TEXT NOT NULL DEFAULT '[]'"),
    ("visibility_json", "TEXT NOT NULL DEFAULT '{}'"),
    ("retention_until", "TEXT"),
)


def _table_exists(connection: sqlite3.Connection, name: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
    ).fetchone()
    return row is not None


def _column_names(connection: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")}


def _create_v2(connection: sqlite3.Connection) -> None:
    connection.executescript(_BASE_TABLES)
    connection.execute(f"CREATE TABLE IF NOT EXISTS atoms ({ATOM_COLUMNS_V2})")


def _upgrade_v1_to_v2(connection: sqlite3.Connection) -> None:
    """Add the four memory dimensions to a first-version atoms table.

    The old `time` column recorded when ingestion ran, which is the only timestamp a
    legacy row honestly has, so it is renamed rather than duplicated.
    """
    columns = _column_names(connection, "atoms")
    if "time" in columns and "ingested_at" not in columns:
        connection.execute("ALTER TABLE atoms RENAME COLUMN time TO ingested_at")
        columns = _column_names(connection, "atoms")
    if "ingested_at" not in columns:
        raise SystemExit(
            "atoms table has neither `time` nor `ingested_at`; refusing to guess which timestamp is ingestion"
        )
    for name, definition in _V1_TO_V2_COLUMNS:
        if name not in columns:
            connection.execute(f"ALTER TABLE atoms ADD COLUMN {name} {definition}")


def apply(connection: sqlite3.Connection) -> None:
    """Bring the schema to SCHEMA_VERSION, in place, without losing rows."""
    version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if version > SCHEMA_VERSION:
        raise SystemExit(f"database schema is version {version}, this build understands {SCHEMA_VERSION}")
    if version == SCHEMA_VERSION:
        return

    if _table_exists(connection, "atoms"):
        connection.executescript(_BASE_TABLES)
        if version < 2:
            _upgrade_v1_to_v2(connection)
    else:
        _create_v2(connection)
    if version < 3:
        _rebuild_fts(connection)

    connection.executescript(VIEWS)
    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


def _rebuild_fts(connection: sqlite3.Connection) -> None:
    """Re-index every atom through text_index: rows indexed before it existed hold raw text, and
    FTS5 cannot match 钥匙 inside a token that is a whole Chinese sentence."""
    connection.execute("DROP TABLE IF EXISTS atom_fts")
    connection.executescript(_BASE_TABLES)
    rows = connection.execute("SELECT atom_id, source, text FROM atoms ORDER BY atom_id").fetchall()
    connection.executemany(
        "INSERT INTO atom_fts(atom_id, source, text) VALUES (?, ?, ?)",
        [(row[0], index_text(row[1]), index_text(row[2])) for row in rows],
    )
