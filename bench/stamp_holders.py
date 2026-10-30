"""Give every ingested atom the holder, scenario and event time the corpus index already states.

The pre-P0 store was built before the memory model had those columns, so it holds 165,973 memories
nobody owns. The frozen corpus index names the owner, the setting and the moment for each source —
the same facts the counterpart and the gold scopes are written from — so the store can be brought
in line without re-running ingestion.

Run: python -m bench.stamp_holders [--store bench/runs/baseline/data/elysian.sqlite]
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from bench.sets_common import MODALITIES, SETS, read_jsonl, record_path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_STORE = REPO / "bench" / "runs" / "baseline" / "data" / "elysian.sqlite"


def corpus_facts() -> dict[str, tuple[str, str, str]]:
    """Absolute path -> (holder, scenario, observed_at), as the frozen corpus index states them."""
    facts: dict[str, tuple[str, str, str]] = {}
    for modality in MODALITIES:
        for record in read_jsonl(SETS / "corpus" / f"{modality}.jsonl"):
            for key in ("holder", "scenario", "observed_at"):
                if not record.get(key):
                    raise SystemExit(f"{modality}: corpus record {record['source_id']} has no {key}")
            facts[str(record_path(record).resolve())] = (
                str(record["holder"]),
                str(record["scenario"]),
                str(record["observed_at"]),
            )
    if not facts:
        raise SystemExit("no corpus index found, run python -m bench.build_sets first")
    return facts


def stamp(store: Path) -> dict[str, int]:
    """Write the corpus facts onto every atom; the store's own source ids stay untouched."""
    if not store.is_file():
        raise SystemExit(f"{store}: no baseline database, run python -m bench.ingest_baseline first")
    facts = corpus_facts()
    with sqlite3.connect(store) as connection:
        rows = connection.execute("SELECT source_id, path FROM sources").fetchall()
        if not rows:
            raise SystemExit(f"{store}: the sources table is empty")
        unknown = sorted(str(path) for _, path in rows if str(path) not in facts)
        if unknown:
            raise SystemExit(f"{store}: {len(unknown)} source paths are not corpus files, first {unknown[:3]}")
        stamped_atoms = 0
        for source_id, path in rows:
            holder, scenario, observed_at = facts[str(path)]
            cursor = connection.execute(
                "UPDATE atoms SET holder_id = ?, scenario = ?, event_time = ?, event_time_precision = 'instant' "
                "WHERE source_id = ?",
                (holder, scenario, observed_at, str(source_id)),
            )
            stamped_atoms += int(cursor.rowcount)
        left = int(connection.execute("SELECT count(*) FROM atoms WHERE holder_id = ''").fetchone()[0])
    return {"sources": len(rows), "atoms": stamped_atoms, "atoms_without_holder": left}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", type=Path, default=DEFAULT_STORE)
    args = parser.parse_args()
    counts = stamp(args.store)
    print(
        f"stamped {counts['atoms']} atoms across {counts['sources']} sources; "
        f"{counts['atoms_without_holder']} atoms still have no holder"
    )


if __name__ == "__main__":
    main()
