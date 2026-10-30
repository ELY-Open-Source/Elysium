from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import zstandard as zstd

from . import cartridge_store
from .config import Settings, get_settings
from .db import Database
from .kv_fingerprint import compute_fingerprint, fingerprint_diff, unverifiable_fields
from .runtime_schemas import AdapterManifest
from .schemas import (
    CartridgeManifest,
    EvidenceAtom,
    MountState,
    SourceRecord,
    utc_now,
)

JSON_PARQUET_COLUMNS = (
    "embedding_refs",
    "layout",
    "relations",
    "trust",
    "metadata",
    "visibility",
)


class CartridgeService:
    def __init__(self, settings: Settings | None = None, database: Database | None = None) -> None:
        self.settings = settings or get_settings()
        self.db = database or Database(self.settings)

    def materialize(
        self,
        name: str,
        atoms: list[EvidenceAtom],
        sources: list[SourceRecord],
    ) -> CartridgeManifest:
        created_at = datetime.now(UTC)
        cartridge_id = self._cartridge_id(name, created_at)
        root = self.settings.cartridge_dir / cartridge_id
        eval_dir = root / "eval_proofs"
        root.mkdir(parents=True, exist_ok=True)
        eval_dir.mkdir(parents=True, exist_ok=True)

        atoms_path = root / "atoms.parquet"
        sources_path = root / "sources.json"
        sparse_path = root / "sparse_index.bm25.zst"
        graph_path = root / "temporal_graph.sqlite"

        self._write_atoms_parquet(atoms_path, atoms)
        sources_path.write_text(
            json.dumps([source.model_dump(mode="json") for source in sources], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._write_sparse_index(sparse_path, atoms)
        self._write_graph(graph_path, atoms)

        manifest = CartridgeManifest(
            cartridge_id=cartridge_id,
            name=name,
            created_at=created_at,
            model_base=self.settings.model_id,
            source_count=len(sources),
            atom_count=len(atoms),
            token_equivalent=sum(atom.token_equivalent for atom in atoms),
            kv_fingerprint=compute_fingerprint(self.settings, root / "adapters"),
            artifacts={
                "manifest": "manifest.json",
                "atoms": "atoms.parquet",
                "sources": "sources.json",
                "sparse_index": "sparse_index.bm25.zst",
                "temporal_graph": "temporal_graph.sqlite",
                "eval_proofs": "eval_proofs/",
            },
        )
        self._commit(manifest, root)
        cartridge_store.set_membership(self.db, cartridge_id, [atom.atom_id for atom in atoms])
        return manifest

    def compute_dna(self, root: Path) -> str:
        digest = hashlib.sha256()
        for path in sorted(root.rglob("*")):
            if path.is_dir() or path.name in {"manifest.json", "proof_suite.json", "cartridge_assets.json"}:
                continue
            digest.update(path.relative_to(root).as_posix().encode("utf-8"))
            with path.open("rb") as handle:
                shutil.copyfileobj(handle, _DigestWriter(digest))
        return digest.hexdigest()

    def list_manifests(self) -> list[CartridgeManifest]:
        manifests: list[CartridgeManifest] = []
        for row in self.db.list_cartridges():
            manifests.append(CartridgeManifest.model_validate_json(row["manifest_json"]))
        return manifests

    def mount_state(self) -> MountState:
        mounted = cartridge_store.mounted_ids(self.db)
        return MountState(
            mounted=mounted,
            scoped=bool(mounted),
            atoms_in_scope=len(cartridge_store.atoms_of_cartridges(self.db, mounted)),
        )

    def mount(self, cartridge_id: str) -> CartridgeManifest:
        """Add one cartridge to the mounted set; a mounted search answers only from it."""
        root, manifest = self._require(cartridge_id)
        self._refuse_if_incompatible(manifest, root)
        mounted = cartridge_store.mounted_ids(self.db)
        if cartridge_id not in mounted:
            cartridge_store.set_mounts(self.db, [*mounted, cartridge_id], utc_now())
        return manifest

    def switch(self, cartridge_id: str) -> CartridgeManifest:
        """Mount one cartridge and nothing else."""
        root, manifest = self._require(cartridge_id)
        self._refuse_if_incompatible(manifest, root)
        cartridge_store.set_mounts(self.db, [cartridge_id], utc_now())
        return manifest

    def unmount(self, cartridge_id: str) -> MountState:
        self._require(cartridge_id)
        mounted = cartridge_store.mounted_ids(self.db)
        if cartridge_id not in mounted:
            raise ValueError(f"{cartridge_id} is not mounted; nothing to unmount")
        cartridge_store.set_mounts(
            self.db, [held for held in mounted if held != cartridge_id], utc_now()
        )
        return self.mount_state()

    def append(self, cartridge_id: str, atom_ids: list[str]) -> CartridgeManifest:
        """Add memories to an existing cartridge; the bundle and its DNA follow the membership."""
        self._require(cartridge_id)
        if not atom_ids:
            raise ValueError("append needs at least one atom")
        atoms = self.db.get_atoms(atom_ids)
        found = {atom.atom_id for atom in atoms}
        missing = [atom_id for atom_id in atom_ids if atom_id not in found]
        if missing:
            raise ValueError(f"cannot append, these atoms are not in the store: {', '.join(missing)}")
        cartridge_store.add_membership(self.db, cartridge_id, atom_ids)
        held = self.db.get_atoms(sorted(cartridge_store.atoms_of_cartridge(self.db, cartridge_id)))
        sources = self.db.get_sources(sorted({atom.source_id for atom in held}))
        return self.rebuild(cartridge_id, held, sources)

    def _require(self, cartridge_id: str) -> tuple[Path, CartridgeManifest]:
        rows = [row for row in self.db.list_cartridges() if row["cartridge_id"] == cartridge_id]
        if not rows:
            raise ValueError(f"Unknown cartridge: {cartridge_id}")
        row = rows[0]
        return Path(row["root_path"]), CartridgeManifest.model_validate_json(row["manifest_json"])

    def _refuse_if_incompatible(self, manifest: CartridgeManifest, root: Path) -> None:
        """KV bytes are only valid under the settings that produced them."""
        stored = manifest.kv_fingerprint
        if stored is None:
            raise ValueError(f"{manifest.cartridge_id} carries no kv fingerprint; rebuild it before mounting")
        live = compute_fingerprint(self.settings, root / "adapters")
        gaps = unverifiable_fields(live)
        if gaps:
            raise ValueError(
                f"cannot verify {manifest.cartridge_id} on this machine: {', '.join(gaps)} are unknown; "
                "set ELYSIAN_MODEL_DIR to the model snapshot"
            )
        differences = fingerprint_diff(stored, live)
        if differences:
            raise ValueError(
                f"{manifest.cartridge_id} was built for a different runtime; refusing to mount: "
                + "; ".join(differences)
            )

    def _commit(self, manifest: CartridgeManifest, root: Path) -> None:
        """Re-hash the bundle, then record the manifest that describes those bytes."""
        manifest.dna = self.compute_dna(root)
        (root / "manifest.json").write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
        self.db.write_cartridge(
            cartridge_id=manifest.cartridge_id,
            name=manifest.name,
            root_path=root,
            manifest_json=manifest.model_dump_json(),
            dna=manifest.dna,
            token_equivalent=manifest.token_equivalent,
            created_at=manifest.created_at,
        )

    def rebuild(
        self,
        cartridge_id: str,
        atoms: list[EvidenceAtom],
        sources: list[SourceRecord],
    ) -> CartridgeManifest:
        root, manifest = self._require(cartridge_id)
        root.mkdir(parents=True, exist_ok=True)

        self._write_atoms_parquet(root / "atoms.parquet", atoms)
        (root / "sources.json").write_text(
            json.dumps([source.model_dump(mode="json") for source in sources], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._write_sparse_index(root / "sparse_index.bm25.zst", atoms)
        self._write_graph(root / "temporal_graph.sqlite", atoms)

        manifest.source_count = len(sources)
        manifest.atom_count = len(atoms)
        manifest.token_equivalent = sum(atom.token_equivalent for atom in atoms)
        manifest.artifacts.update(
            {
                "manifest": "manifest.json",
                "atoms": "atoms.parquet",
                "sources": "sources.json",
                "sparse_index": "sparse_index.bm25.zst",
                "temporal_graph": "temporal_graph.sqlite",
                "eval_proofs": "eval_proofs/",
            }
        )
        manifest.dna = self.compute_dna(root)
        (root / "manifest.json").write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
        self._commit(manifest, root)
        return manifest

    def attach_adapter(self, cartridge_id: str, adapter_dir: Path) -> CartridgeManifest:
        root, manifest = self._require(cartridge_id)
        adapter_manifest_path = adapter_dir / "adapter_manifest.json"
        if not adapter_manifest_path.exists():
            raise ValueError(f"Missing adapter manifest: {adapter_manifest_path}")
        adapter_manifest = AdapterManifest.model_validate_json(
            adapter_manifest_path.read_text(encoding="utf-8")
        )
        adapter_root = root / "adapters" / adapter_manifest.kind.value
        adapter_root.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(adapter_dir, adapter_root, dirs_exist_ok=True)
        manifest.artifacts[f"adapter_{adapter_manifest.kind.value}"] = (
            adapter_root.relative_to(root).as_posix() + "/"
        )
        self._commit(manifest, root)
        return manifest

    def update_artifacts(
        self,
        cartridge_id: str,
        artifacts: dict[str, str],
        token_equivalent: int | None = None,
    ) -> CartridgeManifest:
        root, manifest = self._require(cartridge_id)
        manifest.artifacts.update(artifacts)
        if token_equivalent is not None:
            manifest.token_equivalent = token_equivalent
        self._commit(manifest, root)
        return manifest

    def attach_eval_proof(self, cartridge_id: str, proof_dir: Path) -> CartridgeManifest:
        root, manifest = self._require(cartridge_id)
        if not proof_dir.exists() or not proof_dir.is_dir():
            raise ValueError(f"Missing proof directory: {proof_dir}")
        target = root / "eval_proofs" / proof_dir.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(proof_dir, target, dirs_exist_ok=True)
        manifest.artifacts[f"eval_proof_{proof_dir.name}"] = target.relative_to(root).as_posix() + "/"
        self._commit(manifest, root)
        return manifest

    def _write_atoms_parquet(self, path: Path, atoms: list[EvidenceAtom]) -> None:
        rows = []
        for atom in atoms:
            row = atom.model_dump(mode="json")
            for field in JSON_PARQUET_COLUMNS:
                row[field] = json.dumps(row[field], ensure_ascii=False, sort_keys=True)
            rows.append(row)
        # Parquet cannot write an empty struct column, and a memory atom carries metadata={}.
        table = pa.Table.from_pylist(rows) if rows else pa.Table.from_pydict({"atom_id": []})
        pq.write_table(table, path, compression="zstd")

    def _write_sparse_index(self, path: Path, atoms: list[EvidenceAtom]) -> None:
        payload = [
            {"atom_id": atom.atom_id, "source": atom.source, "text": atom.text, "relations": atom.relations}
            for atom in atoms
        ]
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        compressor = zstd.ZstdCompressor(level=9)
        path.write_bytes(compressor.compress(data))

    def _write_graph(self, path: Path, atoms: list[EvidenceAtom]) -> None:
        connection = sqlite3.connect(path)
        try:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS nodes (
                    atom_id TEXT PRIMARY KEY,
                    modality TEXT NOT NULL,
                    source TEXT NOT NULL,
                    token_equivalent INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS edges (
                    from_atom_id TEXT NOT NULL,
                    to_atom_id TEXT NOT NULL,
                    relation TEXT NOT NULL
                );
                """
            )
            connection.execute("DELETE FROM edges")
            connection.execute("DELETE FROM nodes")
            connection.executemany(
                "INSERT OR REPLACE INTO nodes(atom_id, modality, source, token_equivalent) VALUES (?, ?, ?, ?)",
                [(atom.atom_id, atom.modality.value, atom.source, atom.token_equivalent) for atom in atoms],
            )
            edge_rows: list[tuple[str, str, str]] = []
            known_ids = {atom.atom_id for atom in atoms}
            for atom in atoms:
                for relation in atom.relations:
                    if ":" not in relation:
                        continue
                    relation_name, target = relation.split(":", 1)
                    if target in known_ids:
                        edge_rows.append((atom.atom_id, target, relation_name))
            connection.executemany(
                "INSERT INTO edges(from_atom_id, to_atom_id, relation) VALUES (?, ?, ?)",
                edge_rows,
            )
            connection.commit()
        finally:
            connection.close()

    def _cartridge_id(self, name: str, created_at: datetime) -> str:
        raw = f"{name}:{created_at.isoformat()}".encode()
        safe_name = "".join(char if char.isalnum() else "_" for char in name.lower()).strip("_")[:40]
        return f"{safe_name or 'cartridge'}_{hashlib.sha256(raw).hexdigest()[:12]}"


class _DigestWriter:
    def __init__(self, digest: hashlib._Hash) -> None:
        self.digest = digest

    def write(self, data: bytes) -> int:
        self.digest.update(data)
        return len(data)
