"""The dense leg lives in the database, so a memory is findable the moment it is written.

The first version kept the vectors in `cache/dense_index.npy` plus a JSON list of atom ids.
That pair had no owner: nothing noticed when an atom was added, changed or forgotten, so a
search answered from a snapshot of the past and `forget` had to delete the whole file. Here the
vectors sit in the same SQLite file as the atoms, in a `vec0` table the `sqlite-vec` extension
answers, and the only rule the index has is "one row per current atom, re-encode what changed".
"""

from __future__ import annotations

import hashlib
import sqlite3
import time
from typing import Any

import numpy as np

from .cartridge_store import atoms_of_cartridges
from .config import Settings, get_settings
from .db import Database
from .embeddings import EmbeddingService
from .row_codec import to_json

# The vec0 schema cannot be altered in place, so the format tag is load-bearing: changing the
# vector width or the model means dropping the table and re-encoding, not migrating it.
FORMAT = "ely-eye-dense-vectors-v1"
TABLE = "vec_atoms"
META_TABLE = "vector_index_meta"
BATCH = 64
# A vec0 table has no index on atom_id, so a delete by id scans the table: ids go in as sets.
DELETE_CHUNK = 20_000
# The engine is asked wider than the answer: the boundary check afterwards drops candidates.
CANDIDATE_FLOOR = 100
# A selective filter thins the wide ask, so the search widens once — never twice.
CANDIDATE_CEILING = 1_024
# A scope is narrowed inside the engine by id list only while it is small enough to name.
SCOPE_NARROW_MAX = 2_000


def load_extension(connection: sqlite3.Connection) -> None:
    """Register sqlite-vec and the stamp function on one connection; every connection that
    touches vec0 needs both, and the stamp is compared in SQL so a sync never reads the
    whole corpus of text into Python."""
    if not hasattr(connection, "enable_load_extension"):
        raise SystemExit(
            "this Python's sqlite3 cannot load extensions, and the dense index needs sqlite-vec; "
            "use a sqlite3 built with SQLITE_ENABLE_LOAD_EXTENSION"
        )
    connection.enable_load_extension(True)
    try:
        import sqlite_vec
    except ImportError as error:
        raise SystemExit(
            "the dense index needs the sqlite-vec extension; install it with `pip install sqlite-vec`"
        ) from error
    sqlite_vec.load(connection)
    connection.create_function("atom_stamp", 2, atom_stamp, deterministic=True)


class VectorIndex:
    """One float32 vector per current atom: the writer keeps it, the reader asks it questions."""

    def __init__(
        self, settings: Settings | None = None, database: Database | None = None, embeddings: EmbeddingService | None = None
    ) -> None:
        self.settings = settings or get_settings()
        self.db = database or Database(self.settings)
        self.embeddings = embeddings or EmbeddingService(self.settings, self.db)

    def ensure(self, connection: sqlite3.Connection, dim: int) -> None:
        """Create the table, or rebuild it when the model behind the vectors changed."""
        meta = self._meta(connection)
        wanted = {"format": FORMAT, "dim": str(dim), "model": self.settings.embedding_model_id}
        if meta and all(meta.get(key) == value for key, value in wanted.items()):
            return
        if meta:
            self._rebuild(connection)
        connection.executescript(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS vec_atoms USING vec0(
                embedding float[{dim}] distance_metric=cosine,
                atom_id TEXT,
                stamp TEXT
            );
            """.replace("{dim}", str(dim))
        )
        for key, value in wanted.items():
            connection.execute(
                "INSERT INTO vector_index_meta (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    def sync(self) -> dict[str, Any]:
        """Encode what is missing or stale; the repair path, not the per-query path."""
        started = time.monotonic()
        with self.db.connect() as connection:
            dim = self.embeddings.probe_dim()
            self.ensure(connection, dim)
            stale = self._stale(connection)
            if not stale:
                return {"encoded": 0, "dim": dim, "model": self.settings.embedding_model_id, "seconds": 0.0}
            vectors = self.embeddings.encode_atoms([atom for _, atom in stale])
            self._write(connection, stale, vectors)
        return {
            "encoded": len(stale),
            "dim": int(dim),
            "model": self.settings.embedding_model_id,
            "seconds": round(time.monotonic() - started, 2),
        }

    def sync_atoms(self, atom_ids: list[str]) -> dict[str, Any]:
        """Bring the index in step with memories as they are written.

        Nothing on the search path rebuilds, so this is the half that keeps "written now,
        findable now" true; a memory that has closed or been forgotten loses its vector here too.
        """
        wanted = [atom_id for atom_id in atom_ids if atom_id]
        if not wanted or not self.settings.dense_embeddings_enabled:
            return {"encoded": 0, "dropped": 0}
        started = time.monotonic()
        with self.db.connect() as connection:
            dim = self.embeddings.probe_dim()
            self.ensure(connection, dim)
            current = self._current(connection, wanted)
            kept = {atom_id for atom_id, _ in current}
            dropped = self._delete(connection, [atom_id for atom_id in wanted if atom_id not in kept])
            if current:
                self._write(connection, current, self.embeddings.encode_atoms([atom for _, atom in current]))
        return {"encoded": len(current), "dropped": dropped, "seconds": round(time.monotonic() - started, 3)}

    def search(
        self,
        query_vector: np.ndarray,
        limit: int,
        *,
        holder: str | None = None,
        scenario: str | None = None,
        source_id: str | None = None,
        modality: str | None = None,
        since: str | None = None,
        until: str | None = None,
        cartridge_ids: list[str] | None = None,
        as_holder: str | None = None,
    ) -> dict[str, float]:
        """Closest memories a search is allowed to show, cosine distance turned into a score.

        The engine answers nearest-neighbour and nothing else; every boundary — closed, retired,
        not yet true, another holder's private memory, the cartridge scope — is checked once
        against the atoms table afterwards. Measured on 153,857 stored vectors: folding those
        boundaries into the KNN as a subquery over `v_atoms_current` costs 48.9 seconds a search,
        and checking them afterwards over the candidates costs 0.2 milliseconds.

        The writer keeps the index current (`sync_atoms`), so a search never waits for a rebuild;
        `stats` and `doctor` say when a store has memories the index has never seen.
        """
        if limit <= 0:
            raise ValueError(f"dense search needs a positive limit, got {limit}")
        scope = None if cartridge_ids is None else sorted(atoms_of_cartridges(self.db, cartridge_ids))
        if scope == []:
            return {}
        narrow = to_json(scope) if scope is not None and len(scope) <= SCOPE_NARROW_MAX else None
        asked = max(limit, CANDIDATE_FLOOR)
        vector = np.asarray(query_vector, dtype=np.float32).tobytes()
        with self.db.connect() as connection:
            if self._dim(connection) is None:
                return {}
            while True:
                ranked = self._ranked(connection, vector, asked, narrow)
                if not ranked:
                    return {}
                allowed = self._allowed(
                    connection,
                    [atom_id for atom_id, _ in ranked],
                    holder=holder,
                    scenario=scenario,
                    source_id=source_id,
                    modality=modality,
                    since=since,
                    until=until,
                    cartridge_ids=cartridge_ids,
                    as_holder=as_holder,
                )
                hits = {atom_id: 1.0 - distance for atom_id, distance in ranked if atom_id in allowed}
                # A filter that keeps little of the wide ask means there are more answers further
                # out; one wider round buys them, and the ceiling keeps the round bounded.
                if len(hits) >= limit or len(ranked) < asked or asked >= CANDIDATE_CEILING:
                    break
                asked = min(asked * 4, CANDIDATE_CEILING)
        return dict(sorted(hits.items(), key=lambda item: -item[1])[:limit])

    def _ranked(
        self, connection: sqlite3.Connection, vector: bytes, asked: int, narrow: str | None
    ) -> list[tuple[str, float]]:
        """The engine's own answer: nearest vectors, narrowed to a scope only when the scope is small."""
        return [
            (str(row["atom_id"]), float(row["distance"]))
            for row in connection.execute(
                """
                SELECT atom_id, distance FROM vec_atoms
                WHERE embedding MATCH ? AND k = ?
                  AND (? IS NULL OR atom_id IN (SELECT value FROM json_each(?)))
                ORDER BY distance
                """,
                (vector, asked, narrow, narrow),
            ).fetchall()
        ]

    def _allowed(
        self,
        connection: sqlite3.Connection,
        atom_ids: list[str],
        *,
        holder: str | None,
        scenario: str | None,
        source_id: str | None,
        modality: str | None,
        since: str | None,
        until: str | None,
        cartridge_ids: list[str] | None,
        as_holder: str | None,
    ) -> set[str]:
        """Which candidates this search may show, asked of the atoms table in one statement.

        The currency rules repeat `v_atoms_current` here on purpose: the view answers this
        question with a full scan (77ms over 153,857 atoms) while the atoms table answers it
        through the atom_id index in 0.2ms, and a search cannot afford the scan. The scope is
        checked here rather than in the engine so the rule lives in one place; the engine's id
        list is only a narrowing.
        """
        rows = connection.execute(
            """
            SELECT atom_id FROM atoms
            WHERE atom_id IN (SELECT value FROM json_each(?))
              AND (valid_to IS NULL OR valid_to > strftime('%Y-%m-%dT%H:%M:%f+00:00', 'now'))
              AND (valid_from IS NULL OR valid_from <= strftime('%Y-%m-%dT%H:%M:%f+00:00', 'now'))
              AND (retention_until IS NULL OR retention_until >= strftime('%Y-%m-%dT%H:%M:%f+00:00', 'now'))
              AND (? IS NULL OR holder_id = ?)
              AND (? IS NULL OR scenario = ?)
              AND (? IS NULL OR source_id = ?)
              AND (? IS NULL OR modality = ?)
              AND (? IS NULL OR (event_time IS NOT NULL AND event_time >= ?))
              AND (? IS NULL OR (event_time IS NOT NULL AND event_time <= ?))
              AND (? IS NULL OR EXISTS (
                    SELECT 1 FROM cartridge_atoms AS ca
                    WHERE ca.atom_id = atoms.atom_id
                      AND ca.cartridge_id IN (SELECT value FROM json_each(?))
              ))
              AND (? IS NULL OR holder_id = ''
                    OR json_extract(visibility_json, '$.scope') = 'everyone'
                    OR holder_id = ?
                    OR EXISTS (
                          SELECT 1 FROM json_each(json_extract(visibility_json, '$.holders'))
                          WHERE value = ?
                    ))
            """,
            (
                to_json(atom_ids),
                holder,
                holder,
                scenario,
                scenario,
                source_id,
                source_id,
                modality,
                modality,
                since,
                since,
                until,
                until,
                None if cartridge_ids is None else to_json(cartridge_ids),
                None if cartridge_ids is None else to_json(cartridge_ids),
                as_holder,
                as_holder,
                as_holder,
            ),
        ).fetchall()
        return {str(row["atom_id"]) for row in rows}

    def drop_atoms(self, atom_ids: list[str]) -> int:
        """A forgotten memory must stop answering from the vector side too."""
        with self.db.connect() as connection:
            return self._delete(connection, atom_ids)

    def stats(self) -> dict[str, Any]:
        with self.db.connect() as connection:
            meta = self._meta(connection)
            if not meta:
                return {"built": False, "format": None, "dim": 0, "vectors": 0, "expected": 0, "pending": 0}
            rows = connection.execute("SELECT count(*) AS n FROM vec_atoms").fetchone()["n"]
            expected = _expected(connection)
            pending = len(self._stale(connection))
        return {
            "built": True,
            "format": meta.get("format"),
            "dim": int(meta.get("dim", "0")),
            "model": meta.get("model"),
            "vectors": int(rows),
            "expected": int(expected),
            "pending": pending,
        }

    def _meta(self, connection: sqlite3.Connection) -> dict[str, str]:
        if not _table_exists(connection, META_TABLE):
            return {}
        return {
            str(row["key"]): str(row["value"])
            for row in connection.execute("SELECT key, value FROM vector_index_meta")
        }

    def _dim(self, connection: sqlite3.Connection) -> int | None:
        dim = self._meta(connection).get("dim")
        return None if dim is None else int(dim)

    def _rebuild(self, connection: sqlite3.Connection) -> None:
        """The vectors no longer describe what is stored: start the table over."""
        connection.execute("DROP TABLE IF EXISTS vec_atoms")

    def _delete(self, connection: sqlite3.Connection, atom_ids: list[str]) -> int:
        if not atom_ids or self._dim(connection) is None:
            return 0
        removed = 0
        for start in range(0, len(atom_ids), DELETE_CHUNK):
            stop = min(start + DELETE_CHUNK, len(atom_ids))
            removed += connection.execute(
                "DELETE FROM vec_atoms WHERE atom_id IN (SELECT value FROM json_each(?))",
                (to_json(atom_ids[start:stop]),),
            ).rowcount
        return removed

    def _current(self, connection: sqlite3.Connection, atom_ids: list[str]) -> list[tuple[str, Any]]:
        """The written memories that still deserve a vector: open, and with words."""
        from .row_codec import row_to_atom

        rows = connection.execute(
            """
            SELECT * FROM v_atoms_current
            WHERE atom_id IN (SELECT value FROM json_each(?)) AND text IS NOT NULL AND text != ''
            """,
            (to_json(atom_ids),),
        ).fetchall()
        return [(str(row["atom_id"]), row_to_atom(row)) for row in rows]

    def _write(self, connection: sqlite3.Connection, items: list[tuple[str, Any]], vectors: np.ndarray) -> None:
        """Replace these atoms' rows: the ids are deleted as sets, then the vectors go in.

        Deleting one memory at a time was quadratic on a real corpus — a vec0 table has no index
        on atom_id, so each delete re-scans every vector already stored.
        """
        if len(vectors) != len(items):
            raise ValueError(f"sync encoded {len(vectors)} vectors for {len(items)} atoms")
        matrix = np.asarray(vectors, dtype=np.float32)
        if matrix.ndim != 2 or matrix.shape[1] != self._dim(connection):
            raise ValueError(f"sync produced a {matrix.shape} matrix, expected one row per atom at the stored width")
        ids = [atom_id for atom_id, _ in items]
        for start in range(0, len(ids), DELETE_CHUNK):
            stop = min(start + DELETE_CHUNK, len(ids))
            connection.execute(
                "DELETE FROM vec_atoms WHERE atom_id IN (SELECT value FROM json_each(?))", (to_json(ids[start:stop]),)
            )
        for start in range(0, len(items), BATCH):
            stop = min(start + BATCH, len(items))
            connection.executemany(
                "INSERT INTO vec_atoms (embedding, atom_id, stamp) VALUES (?, ?, ?)",
                [
                    (matrix[index].tobytes(), atom_id, _stamp(atom))
                    for index, (atom_id, atom) in enumerate(items[start:stop], start=start)
                ],
            )

    def _stale(self, connection: sqlite3.Connection) -> list[tuple[str, Any]]:
        """Current memories the index does not hold, or holds from an older version of the memory.

        A memory with no words is the visual index's job, so it never reaches this table. The
        stored stamps are copied into a temp table first: a vec0 table has no index on atom_id,
        so joining it straight against the atoms scans every vector once per atom — hours on a
        real corpus where the copy makes it one scan each.
        """
        from .row_codec import row_to_atom

        connection.executescript(
            "DROP TABLE IF EXISTS temp.dense_seen;\n"
            "CREATE TEMP TABLE dense_seen (atom_id TEXT PRIMARY KEY, stamp TEXT);\n"
            "INSERT INTO dense_seen SELECT atom_id, stamp FROM vec_atoms;"
        )
        rows = connection.execute(
            """
            SELECT a.* FROM v_atoms_current AS a
            LEFT JOIN dense_seen AS d ON d.atom_id = a.atom_id
            WHERE a.text IS NOT NULL AND a.text != ''
              AND (d.atom_id IS NULL OR d.stamp IS NULL OR d.stamp != atom_stamp(a.ingested_at, a.text))
            ORDER BY a.atom_id
            """
        ).fetchall()
        return [(str(row["atom_id"]), row_to_atom(row)) for row in rows]


def atom_stamp(ingested_at: str, text: str | None) -> str:
    digest = hashlib.sha256((text or "").encode("utf-8", "replace")).hexdigest()[:16]
    return f"{ingested_at}:{digest}"


def expected_vectors(database: Database) -> int:
    """Memories this index is meant to hold: the open ones that have words."""
    with database.connect() as connection:
        return _expected(connection)


def _expected(connection: sqlite3.Connection) -> int:
    row = connection.execute(
        "SELECT count(*) AS n FROM v_atoms_current WHERE text IS NOT NULL AND text != ''"
    ).fetchone()
    return int(row["n"])


def _stamp(atom: Any) -> str:
    return atom_stamp(atom.ingested_at.isoformat(), atom.text)


def _table_exists(connection: sqlite3.Connection, name: str) -> bool:
    return (
        connection.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)).fetchone() is not None
    )
