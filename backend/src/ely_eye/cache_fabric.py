from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from .config import Settings, get_settings
from .db import Database
from .status_schemas import CacheLayerStatus

SEMANTIC_LAYER = "semantic"


class CacheFabric:
    def __init__(self, settings: Settings | None = None, database: Database | None = None) -> None:
        self.settings = settings or get_settings()
        self.db = database or Database(self.settings)

    def semantic_key(self, question: str, profile: str, store_revision: int, holder: str = "") -> str:
        """A compiled context is only true for the corpus it was compiled from and the eyes that were allowed to see it, so both belong in its name."""
        return hashlib.sha256(f"compiler-v2\n{profile}\n{store_revision}\n{holder}\n{question}".encode()).hexdigest()

    def record_hit(self, layer: str, cache_key: str, bytes_estimate: int = 0, metadata: dict[str, Any] | None = None) -> None:
        self.db.log_cache_event(layer, cache_key, "hit", bytes_estimate, metadata)

    def record_miss(self, layer: str, cache_key: str, bytes_estimate: int = 0, metadata: dict[str, Any] | None = None) -> None:
        self.db.log_cache_event(layer, cache_key, "miss", bytes_estimate, metadata)

    def write_semantic_cache(self, cache_key: str, payload: dict[str, Any]) -> None:
        path = self.settings.cache_dir / "semantic" / f"{cache_key}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        path.write_bytes(data)
        self.db.log_cache_event(SEMANTIC_LAYER, cache_key, "write", len(data), {"path": str(path)})

    def read_semantic_cache(self, cache_key: str) -> dict[str, Any] | None:
        """Return the cached payload, or None. The caller traces the event: one compile, one event."""
        path = self.settings.cache_dir / "semantic" / f"{cache_key}.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f"{path}: the semantic cache entry is unreadable ({error})") from error

    def drop_semantic_cache(self) -> int:
        """Delete every compiled context: each one may quote a memory that no longer exists."""
        directory = self.settings.cache_dir / "semantic"
        if not directory.exists():
            return 0
        entries = list(directory.glob("*.json"))
        for path in entries:
            path.unlink()
        return len(entries)

    def statuses(self) -> list[CacheLayerStatus]:
        rows = self.db.cache_layer_rows()
        statuses: list[CacheLayerStatus] = []
        for row in rows:
            last = row["last_event_at"]
            statuses.append(
                CacheLayerStatus(
                    layer=row["layer"],
                    entries=int(row["entries"] or 0),
                    bytes_estimate=int(row["bytes_estimate"] or 0),
                    hit_count=int(row["hit_count"] or 0),
                    miss_count=int(row["miss_count"] or 0),
                    last_event_at=datetime.fromisoformat(last) if last else None,
                )
            )
        return statuses
