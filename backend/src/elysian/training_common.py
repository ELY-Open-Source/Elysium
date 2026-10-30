"""Shared constants, digests and trace writers: the vocabulary every training module speaks."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

from pydantic import BaseModel, Field

from .schemas import TrainingAdapterKind

SYSTEM_PROMPT = (
    "You are Elysian. Answer from supplied evidence, return compact JSON, "
    "and cite atom ids exactly."
)

TRAINING_PROOF_VERSION = 2

TRAINING_METHOD = "BF16 LoRA"

TRAINING_PRECISION = "bf16"

TRAINING_FRAMEWORK = "unsloth_patched_transformers_peft"

GRADIENT_CHECKPOINTING_MODE = "unsloth_patched_torch_non_reentrant"

AUTOCAST_DTYPE = "bf16"

class TrainingSample(BaseModel):
    id: str
    task: str
    inputs: list[dict[str, Any]]
    memory: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any]

class _DigestWriter:
    def __init__(self, digest: hashlib._Hash) -> None:
        self.digest = digest

    def write(self, data: bytes) -> int:
        self.digest.update(data)
        return len(data)

def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        shutil.copyfileobj(handle, _DigestWriter(digest))
    return digest.hexdigest()

def sha256_tree(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name != "adapter_manifest.json":
            digest.update(path.relative_to(root).as_posix().encode("utf-8"))
            with path.open("rb") as handle:
                shutil.copyfileobj(handle, _DigestWriter(digest))
    return digest.hexdigest()

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]+", "-", value).strip("-").lower()
    return slug[:80] or "section"

def adapter_id(kind: TrainingAdapterKind, dataset_path: Path, model_id: str) -> str:
    raw = f"{kind.value}:{model_id}:{dataset_path.resolve()}:{datetime.now(UTC).isoformat()}"
    return f"{kind.value}_{sha256_bytes(raw.encode('utf-8'))[:12]}"

def relative_artifacts(root: Path) -> dict[str, str]:
    artifacts: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name != "adapter_manifest.json":
            artifacts[path.stem] = path.relative_to(root).as_posix()
    return artifacts

def write_jsonl(path: Path, samples: list[TrainingSample]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for sample in samples:
            handle.write(sample.model_dump_json() + "\n")

def write_trace(handle: TextIO, payload: dict[str, Any]) -> None:
    handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
    handle.flush()

def write_training_summary(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

def split_markdown_sections(text: str) -> list[dict[str, str]]:
    matches = list(re.finditer(r"^(#{2,3})\s+(.+?)\s*$", text, flags=re.MULTILINE))
    sections: list[dict[str, str]] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections.append({"title": match.group(2).strip(), "body": text[start:end].strip()})
    return sections

def section_by_title(text: str, title_fragment: str) -> str:
    for section in split_markdown_sections(text):
        if title_fragment in section["title"]:
            return section["body"]
    return ""
