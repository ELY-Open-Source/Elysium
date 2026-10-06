"""Shared helpers for building and validating benchmark annotation sets."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
CORPUS = ROOT / "corpus"
SETS = ROOT / "sets"
# Derived media (images pulled out of parquet, video frames, crops) lives outside
# the repository: tens of thousands of new files inside it swamps repo tooling.
DATA_ROOT = Path(os.environ.get("ELY_EYE_BENCH_DATA", str(Path.home() / "ely_eye_bench_data")))
CORPUS_ROOTS = {"corpus": CORPUS, "derived": DATA_ROOT}
MODALITIES = ("pdf", "image", "ui_screenshot", "video", "code", "conversation")
REQUIRED_QUERY_FIELDS = (
    "query_id",
    "modality",
    "question",
    "answer",
    "answer_format",
    "gold",
    "scope",
    "as_of",
    "unanswerable",
    "origin",
    "split",
)
REQUIRED_CORPUS_FIELDS = (
    "source_id",
    "modality",
    "path",
    "root",
    "title",
    "observed_at",
    "holder",
    "scenario",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


SAFE_ID = re.compile(r"^[A-Za-z0-9_-][A-Za-z0-9._-]*$")
UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def safe_id(value: str, where: str) -> str:
    """Reject upstream identifiers that could escape their directory when used as a name."""
    if not SAFE_ID.match(value) or ".." in value:
        raise SystemExit(f"{where}: unsafe identifier {value!r}")
    return value


def safe_segment(value: str, where: str) -> str:
    """Rewrite an upstream path segment so it cannot escape its directory.

    Unlike safe_id this keeps every dataset row: real repositories contain braces,
    spaces, and unicode. Uniqueness is the caller's job (append a hash of the
    original value when several values could collide).
    """
    cleaned = UNSAFE.sub("-", value).strip(".-")
    if not cleaned or cleaned == "..":
        raise SystemExit(f"{where}: no usable name in {value!r}")
    return cleaned


def as_int(value: Any, where: str) -> int:
    """Parse a third-party numeric field, naming the offending value on failure."""
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise SystemExit(f"{where}: expected an integer, got {value!r}") from exc


def parse_json_object(text: str, where: str) -> dict[str, Any]:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"malformed json at {where}: {exc}") from exc
    if not isinstance(parsed, dict):
        raise SystemExit(f"expected a json object at {where}")
    return parsed


def parse_json_line(text: str, where: str) -> dict[str, Any]:
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"malformed jsonl at {where}: {exc}") from exc


def parse_json_array(text: str, where: str) -> list[Any]:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"malformed json at {where}: {exc}") from exc
    if not isinstance(parsed, list):
        raise SystemExit(f"expected a json array at {where}")
    return parsed


def load_manifest() -> list[dict[str, Any]]:
    manifest = CORPUS / "manifest.jsonl"
    if not manifest.is_file():
        raise SystemExit(f"missing corpus manifest: {manifest} (run bench.fetch_corpus)")
    return [
        parse_json_line(line, f"{manifest}:{number}")
        for number, line in enumerate(manifest.read_text().splitlines(), start=1)
        if line.strip()
    ]


def manifest_index() -> dict[tuple[str, str], dict[str, Any]]:
    return {(row["dataset"], row["path"]): row for row in load_manifest()}


def corpus_path(dataset: str, path: str) -> Path:
    entry = manifest_index().get((dataset, path))
    if entry is None:
        raise SystemExit(f"{dataset}/{path} is not in the frozen corpus manifest")
    target = CORPUS / dataset / path
    if not target.is_file():
        raise SystemExit(f"manifest entry missing on disk: {target}")
    return target


def record_path(record: dict[str, Any]) -> Path:
    """Resolve a corpus record's path against the root named by its 'root' field."""
    root_name = record.get("root")
    if root_name not in CORPUS_ROOTS:
        raise SystemExit(f"unknown corpus root {root_name!r} for {record.get('source_id')}")
    relative = str(record["path"])
    if Path(relative).is_absolute():
        raise SystemExit(f"corpus path must be relative: {relative}")
    return CORPUS_ROOTS[str(root_name)] / relative


def split_for(key: str, dev_modulus: int = 3) -> str:
    """Deterministic split: no RNG, so re-running the builder cannot reshuffle."""
    digest = hashlib.sha256(key.encode()).digest()
    return "dev" if digest[0] % dev_modulus == 0 else "test"


def query_record(
    *,
    query_id: str,
    modality: str,
    question: str,
    answer: str | None,
    answer_format: str,
    gold: list[dict[str, Any]],
    holder: str,
    scenario: str,
    as_of: str,
    origin: dict[str, Any],
    session: str | None = None,
) -> dict[str, Any]:
    unanswerable = answer is None
    if unanswerable and gold:
        raise SystemExit(f"{query_id}: unanswerable queries must have empty gold")
    if not unanswerable and not gold:
        raise SystemExit(f"{query_id}: answerable queries need at least one gold region")
    if modality not in MODALITIES:
        raise SystemExit(f"{query_id}: unknown modality {modality!r}")
    return {
        "query_id": query_id,
        "modality": modality,
        "question": question,
        "answer": answer,
        "answer_format": answer_format,
        "gold": gold,
        "scope": {"holder": holder, "session": session, "scenario": scenario},
        "as_of": as_of,
        "unanswerable": unanswerable,
        "origin": origin,
        "split": split_for(query_id),
    }


def sample_by_holder(
    queries: list[dict[str, Any]], per_holder: int = 40
) -> list[dict[str, Any]]:
    """Deterministic stratified pick so every holder is represented at a fixed size."""
    by_holder: dict[str, list[dict[str, Any]]] = {}
    for query in queries:
        by_holder.setdefault(query["scope"]["holder"], []).append(query)
    picked: list[dict[str, Any]] = []
    for holder in sorted(by_holder):
        rows = sorted(by_holder[holder], key=lambda row: row["query_id"])
        step = max(1, len(rows) // per_holder)
        picked.extend(rows[index] for index in range(0, len(rows), step)[:per_holder])
    return picked


def corpus_record(
    *,
    source_id: str,
    modality: str,
    path: str,
    title: str,
    observed_at: str,
    holder: str,
    scenario: str,
    root: str = "corpus",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if modality not in MODALITIES:
        raise SystemExit(f"{source_id}: unknown modality {modality!r}")
    if root not in CORPUS_ROOTS:
        raise SystemExit(f"{source_id}: unknown corpus root {root!r}")
    record: dict[str, Any] = {
        "source_id": source_id,
        "modality": modality,
        "path": path,
        "root": root,
        "title": title,
        "observed_at": observed_at,
        "holder": holder,
        "scenario": scenario,
    }
    record.update(extra or {})
    return record


def write_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> tuple[int, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
            count += 1
    if count == 0:
        raise SystemExit(f"{path.name}: builder produced zero records")
    return count, sha256_file(path)


def read_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            if line.strip():
                yield parse_json_line(line, f"{path}:{number}")


def validate_query(record: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    missing = [key for key in REQUIRED_QUERY_FIELDS if key not in record]
    if missing:
        problems.append(f"missing fields {missing}")
        return problems
    if record["modality"] not in MODALITIES:
        problems.append(f"unknown modality {record['modality']!r}")
    if record["unanswerable"] != (record["answer"] is None):
        problems.append("unanswerable flag disagrees with answer presence")
    if record["unanswerable"] and record["gold"]:
        problems.append("unanswerable query carries gold regions")
    if not record["unanswerable"] and not record["gold"]:
        problems.append("answerable query has no gold regions")
    for gold in record["gold"]:
        if "source_id" not in gold or "region" not in gold:
            problems.append(f"gold entry missing source_id/region: {gold}")
            continue
        problems.extend(validate_region(record["modality"], gold["region"]))
    scope = record["scope"]
    if not scope.get("holder"):
        problems.append("scope.holder is required")
    if not record["origin"].get("dataset") or not record["origin"].get("revision"):
        problems.append("origin.dataset and origin.revision are required")
    if record["split"] not in ("dev", "test"):
        problems.append(f"bad split {record['split']!r}")
    return problems


def validate_region(modality: str, region: dict[str, Any]) -> list[str]:
    keys = set(region)
    if modality == "pdf" and not keys <= {"page", "block"}:
        return [f"pdf region has unexpected keys {sorted(keys)}"]
    if modality == "ui_screenshot" and keys != {"bbox"}:
        return [f"ui_screenshot region must be exactly {{bbox}}, got {sorted(keys)}"]
    if modality == "video" and not keys <= {"t_start", "t_end"}:
        return [f"video region has unexpected keys {sorted(keys)}"]
    if modality == "code" and keys not in ({"path", "symbol"}, {"path", "line"}):
        return [f"code region must be {{path,symbol}} or {{path,line}}, got {sorted(keys)}"]
    if modality == "conversation" and not keys <= {"turn"}:
        # Empty means the whole session: LongMemEval marks some answers only at session level.
        return [f"conversation region may only hold {{turn}}, got {sorted(keys)}"]
    if modality == "image" and keys:
        return [f"image region must be empty, got {sorted(keys)}"]
    return []


def validate_corpus(record: dict[str, Any]) -> list[str]:
    missing = [key for key in REQUIRED_CORPUS_FIELDS if key not in record]
    if missing:
        return [f"missing fields {missing}"]
    if record["modality"] not in MODALITIES:
        return [f"unknown modality {record['modality']!r}"]
    if record["root"] not in CORPUS_ROOTS:
        return [f"unknown corpus root {record['root']!r}"]
    if not record_path(record).is_file():
        return [f"file missing: {record_path(record)}"]
    return []
