"""Page through the store the way a person browses a shelf: newest first, filtered by who and what."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import Settings
from .db import Database, row_to_atom
from .retrieval import decode_cursor, encode_cursor
from .schemas import AtomPage, Modality
from .storage import ObjectStore


@dataclass(frozen=True)
class Picture:
    """The bytes behind an atom and how to label them when serving."""

    path: Path
    mime: str


def browse(
    settings: Settings,
    *,
    limit: int,
    cursor: str | None = None,
    modality: Modality | None = None,
    source_id: str | None = None,
    holder: str | None = None,
) -> AtomPage:
    """One page plus the total, so a list can say what it left out instead of looking endless."""
    offset = decode_cursor(cursor)
    wanted = (modality.value if modality else None, source_id, holder)
    filters = tuple(value for bound in wanted for value in (bound, bound))
    database = Database(settings)
    with database.connect() as connection:
        total = int(
            connection.execute(
                "SELECT COUNT(*) FROM v_atoms_current WHERE (? IS NULL OR modality = ?) AND (? IS NULL OR source_id = ?) AND (? IS NULL OR holder_id = ?)",
                filters,
            ).fetchone()[0]
        )
        rows = connection.execute(
            "SELECT * FROM v_atoms_current WHERE (? IS NULL OR modality = ?) AND (? IS NULL OR source_id = ?) AND (? IS NULL OR holder_id = ?) ORDER BY ingested_at DESC, atom_id DESC LIMIT ? OFFSET ?",
            (*filters, limit + 1, offset),
        ).fetchall()
    atoms = [row_to_atom(row) for row in rows[:limit]]
    more = len(rows) > limit or offset + limit < total
    return AtomPage(
        atoms=atoms,
        total=total,
        next_cursor=encode_cursor(offset + limit) if atoms and more else None,
    )


def picture(settings: Settings, atom_id: str) -> Picture | None:
    """The stored bytes behind one atom; None means there is no picture to show, for any of the three reasons."""
    database = Database(settings)
    with database.connect() as connection:
        row = connection.execute(
            "SELECT image_ref, mime FROM v_atoms_current JOIN sources USING (source_id) WHERE atom_id = ?",
            (atom_id,),
        ).fetchone()
    if row is None or not row["image_ref"]:
        return None
    path = ObjectStore(settings).resolve(str(row["image_ref"]))
    if not path.exists():
        return None
    mime = str(row["mime"]) if row["mime"] else "image/png"
    return Picture(path=path, mime=mime)
