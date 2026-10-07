"""Membership and mount state for cartridges, kept out of db.py by the size rule.

A cartridge used to exist only as files copied out of the store, so "mount this cartridge"
had nothing to filter against. Membership now lives beside the atoms, and the mount table
is what a search scopes itself to when the caller does not name a scope.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from .db import Database
from .row_codec import to_json
from .schemas import utc_now


def set_membership(database: Database, cartridge_id: str, atom_ids: list[str]) -> None:
    """Replace the atom set a cartridge holds."""
    added_at = utc_now().isoformat()
    with database.connect() as connection:
        connection.execute("DELETE FROM cartridge_atoms WHERE cartridge_id = ?", (cartridge_id,))
        connection.executemany(
            "INSERT OR IGNORE INTO cartridge_atoms(cartridge_id, atom_id, added_at) VALUES (?, ?, ?)",
            [(cartridge_id, atom_id, added_at) for atom_id in atom_ids],
        )


def add_membership(database: Database, cartridge_id: str, atom_ids: list[str]) -> int:
    """Add atoms to a cartridge; returns how many were new."""
    added_at = utc_now().isoformat()
    with database.connect() as connection:
        before = _count(connection, cartridge_id)
        connection.executemany(
            "INSERT OR IGNORE INTO cartridge_atoms(cartridge_id, atom_id, added_at) VALUES (?, ?, ?)",
            [(cartridge_id, atom_id, added_at) for atom_id in atom_ids],
        )
        after = _count(connection, cartridge_id)
    return after - before


def membership_count(database: Database, cartridge_id: str) -> int:
    with database.connect() as connection:
        return _count(connection, cartridge_id)


def cartridges_holding_atom(database: Database, atom_id: str) -> list[str]:
    with database.connect() as connection:
        rows = connection.execute(
            "SELECT cartridge_id FROM cartridge_atoms WHERE atom_id = ? ORDER BY cartridge_id",
            (atom_id,),
        ).fetchall()
    return [str(row["cartridge_id"]) for row in rows]


def atoms_of_cartridge(database: Database, cartridge_id: str) -> list[str]:
    with database.connect() as connection:
        rows = connection.execute(
            "SELECT atom_id FROM cartridge_atoms WHERE cartridge_id = ? ORDER BY atom_id",
            (cartridge_id,),
        ).fetchall()
    return [str(row["atom_id"]) for row in rows]


def atoms_of_cartridges(database: Database, cartridge_ids: list[str]) -> set[str]:
    """Every atom the named cartridges hold; the scope a search must not leak outside."""
    if not cartridge_ids:
        return set()
    with database.connect() as connection:
        rows = connection.execute(
            "SELECT DISTINCT atom_id FROM cartridge_atoms "
            "WHERE cartridge_id IN (SELECT value FROM json_each(?))",
            (to_json(cartridge_ids),),
        ).fetchall()
    return {str(row["atom_id"]) for row in rows}


def mounted_ids(database: Database) -> list[str]:
    with database.connect() as connection:
        rows = connection.execute(
            "SELECT cartridge_id, mounted_at FROM mounts ORDER BY mounted_at, cartridge_id"
        ).fetchall()
    return [str(row["cartridge_id"]) for row in rows]


def set_mounts(database: Database, cartridge_ids: list[str], mounted_at: datetime) -> None:
    """Replace the mounted set; mounting is a whole-state write, not a toggle."""
    stamp = mounted_at.isoformat()
    with database.connect() as connection:
        connection.execute("DELETE FROM mounts")
        connection.executemany(
            "INSERT INTO mounts(cartridge_id, mounted_at) VALUES (?, ?)",
            [(cartridge_id, stamp) for cartridge_id in cartridge_ids],
        )


def clear_mounts(database: Database) -> None:
    with database.connect() as connection:
        connection.execute("DELETE FROM mounts")


def _count(connection: sqlite3.Connection, cartridge_id: str) -> int:
    row = connection.execute(
        "SELECT COUNT(*) AS n FROM cartridge_atoms WHERE cartridge_id = ?", (cartridge_id,)
    ).fetchone()
    return int(row["n"])
