"""Small readers, writers and diggers the proof checks share.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import zstandard as zstd


def parquet_row_count(path: Path) -> int:
    if not path.exists():
        return -1
    import pyarrow.parquet as pq

    return pq.read_metadata(path).num_rows


def compiled_context_digest(context: Any) -> str:
    payload = {
        "hits": [hit.atom.atom_id for hit in context.hits],
        "packed_text": context.packed_text,
        "token_equivalent": context.token_equivalent,
    }
    data = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def read_memory_capsule(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    prefix = b"ELYMEMCAP1\n"
    if not data.startswith(prefix):
        raise ValueError(f"Invalid memory capsule header: {path}")
    try:
        payload = zstd.ZstdDecompressor().decompress(data[len(prefix) :])
        parsed = json.loads(payload.decode("utf-8"))
    except (zstd.ZstdError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"Cannot decode the memory capsule at {path}: {error}") from error
    if not isinstance(parsed, dict):
        raise ValueError(f"Invalid memory capsule payload: {path}")  # noqa: TRY004  # the capsule's own bytes are wrong, not the caller's argument
    return parsed


def validated_segment_hash(segment: dict[str, Any]) -> str:
    expected = segment.get("segment_sha256")
    if not isinstance(expected, str):
        return ""
    payload = {key: value for key, value in segment.items() if key != "segment_sha256"}
    actual = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return actual if actual == expected else ""


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def read_json_or_empty(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def format_scores(scores: dict[str, Any]) -> str:
    parts: list[str] = []
    for name in sorted(scores):
        score = scores[name]
        if isinstance(score, (int, float)) and math.isfinite(float(score)):
            parts.append(f"{name}={float(score):.2f}")
        else:
            parts.append(f"{name}=unscored")
    return ", ".join(parts) or "none"


def is_finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(float(value))


def compact_generation_context(context: Any, section_hint: str, max_chars: int = 2400) -> Any:
    text_hits = [hit for hit in context.hits if hit.atom.modality.value == "text"]
    hits = (text_hits or context.hits)[:1]
    sections: list[str] = []
    for hit in hits:
        atom = hit.atom
        evidence_text = extract_markdown_section(atom.text, section_hint) or atom.text
        evidence_text = evidence_text.strip()[:max_chars]
        citation = {
            "atom_id": atom.atom_id,
            "modality": atom.modality.value,
            "source": atom.source,
            "image_ref": atom.image_ref,
            "layout": atom.layout.model_dump() if atom.layout else None,
            "score": hit.final_score,
        }
        sections.append(f"[EVIDENCE]\n{citation}\n{evidence_text}\n[/EVIDENCE]")
    packed_text = "\n\n".join(sections)
    return context.model_copy(
        update={
            "hits": hits,
            "packed_text": packed_text,
            "token_equivalent": max(1, len(packed_text) // 4),
        }
    )


def extract_markdown_section(text: str, section_hint: str) -> str:
    lines = text.splitlines()
    start = None
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("#") and section_hint in stripped:
            start = index
            break
    if start is None:
        return ""
    end = len(lines)
    start_level = len(lines[start]) - len(lines[start].lstrip("#"))
    for index in range(start + 1, len(lines)):
        stripped = lines[index].strip()
        if stripped.startswith("#"):
            level = len(lines[index]) - len(lines[index].lstrip("#"))
            if level <= start_level:
                end = index
                break
    return "\n".join(lines[start:end])


def relative_artifacts(root: Path) -> dict[str, str]:
    artifacts: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            key = path.relative_to(root).as_posix()
            artifacts[key] = key
    return artifacts
