"""What this store can answer, read back from what it actually holds.

A caller deciding whether to send its questions here needs three facts it cannot guess: who is in
the directory and what they claim to know, whether the memory it would get covers pictures and
speech or only words, and which schema the answers were produced under. Every field is read from
the store, so the card cannot promise a sense the store has no atoms for, and it cannot promise a
capacity a mount has not carried.
"""

from __future__ import annotations

from datetime import datetime

from .card_schemas import CapabilityCard, HolderCard
from .cartridge import CartridgeService
from .config import Settings
from .db import Database
from .holder_store import HolderStore


def build_card(settings: Settings) -> CapabilityCard:
    """The store-level card: schema, counts, senses present, and what is mounted read-only."""

    database = Database(settings)
    with database.connect() as connection:
        schema_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        sources = int(connection.execute("SELECT COUNT(*) FROM sources").fetchone()[0])
        senses = {
            str(row["modality"]): int(row["n"])
            for row in connection.execute(
                "SELECT modality, COUNT(*) AS n FROM v_atoms_current GROUP BY modality ORDER BY n DESC"
            )
        }
        per_holder = {
            str(row["holder_id"]): (int(row["n"]), str(row["newest"]))
            for row in connection.execute(
                "SELECT holder_id, COUNT(*) AS n, MAX(ingested_at) AS newest FROM v_atoms_current"
                " GROUP BY holder_id"
            )
        }
        senses_by_holder: dict[str, dict[str, int]] = {}
        scenarios_by_holder: dict[str, list[str]] = {}
        for row in connection.execute(
            "SELECT holder_id, modality, COUNT(*) AS n FROM v_atoms_current"
            " GROUP BY holder_id, modality ORDER BY n DESC"
        ):
            senses_by_holder.setdefault(str(row["holder_id"]), {})[str(row["modality"])] = int(row["n"])
        for row in connection.execute(
            "SELECT holder_id, scenario, COUNT(*) AS n FROM v_atoms_current"
            " GROUP BY holder_id, scenario HAVING n > 0 ORDER BY n DESC"
        ):
            scenarios_by_holder.setdefault(str(row["holder_id"]), []).append(str(row["scenario"]))

    directory = {entry.holder_id: entry for entry in HolderStore(database).list_holders()}
    cards: dict[str, HolderCard] = {}
    for holder_id, (memories, newest) in per_holder.items():
        entry = directory.get(holder_id)
        cards[holder_id] = HolderCard(
            holder_id=holder_id,
            name=entry.name if entry else "",
            kind=entry.kind if entry else "person",
            knows_about=list(entry.knows_about) if entry else [],
            contact=dict(entry.contact) if entry else {},
            memories=memories,
            modalities=senses_by_holder.get(holder_id, {}),
            scenarios=scenarios_by_holder.get(holder_id, []),
            newest_memory=datetime.fromisoformat(newest),
            registered=entry is not None,
            token_issued=entry is not None and entry.token_issued_at is not None,
        )
    for holder_id, entry in directory.items():
        if holder_id not in cards:
            cards[holder_id] = HolderCard(
                holder_id=holder_id,
                name=entry.name,
                kind=entry.kind,
                knows_about=list(entry.knows_about),
                contact=dict(entry.contact),
                newest_memory=None,
                registered=True,
                token_issued=entry.token_issued_at is not None,
            )

    return CapabilityCard(
        schema_version=schema_version,
        atoms=database.atom_count(),
        sources=sources,
        modalities=senses,
        has_audio="audio" in senses,
        holders=[cards[key] for key in sorted(cards)],
        mounts=CartridgeService(settings).mount_state(),
    )
