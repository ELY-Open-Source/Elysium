"""Score a benchmark prediction: the prompt, the answer match, and the sample normalising."""

import json
import math
import re
from ast import literal_eval
from pathlib import Path
from typing import Any

from .evaluation_schemas import (
    BenchmarkSpec,
)


def get_nested(record: dict[str, Any], path: str) -> Any:
    current: Any = record
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def exact_or_contains_score(prediction: str, answer: str) -> float:
    normalized_prediction = normalize_answer(prediction)
    normalized_answer = normalize_answer(answer)
    if not normalized_prediction or not normalized_answer:
        return 0.0
    if normalized_prediction == normalized_answer or normalized_answer in normalized_prediction:
        return 1.0
    prediction_tokens = normalized_prediction.split()
    answer_tokens = normalized_answer.split()
    if not prediction_tokens or not answer_tokens:
        return 0.0
    overlap = len(set(prediction_tokens) & set(answer_tokens))
    precision = overlap / len(set(prediction_tokens))
    recall = overlap / len(set(answer_tokens))
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def benchmark_score(
    benchmark: BenchmarkSpec,
    row: dict[str, Any],
    prediction: str,
    answer: str | None,
) -> float | None:
    if answer is None:
        return None
    if "multiple_choice" in benchmark.task_type:
        option_text = answer_option_text(row, answer)
        if exact_or_contains_score(prediction, answer):
            return 1.0
        if option_text and exact_or_contains_score(prediction, option_text):
            return 1.0
        return 0.0
    return exact_or_contains_score(prediction, answer)


def answer_option_text(row: dict[str, Any], answer: str) -> str | None:
    normalized_answer = answer.strip().upper()
    if len(normalized_answer) != 1 or not normalized_answer.isalpha():
        return None
    options = row.get("options")
    if isinstance(options, str):
        try:
            options = literal_eval(options)
        except (SyntaxError, ValueError):
            options = None
    index = ord(normalized_answer) - ord("A")
    if isinstance(options, (list, tuple)) and 0 <= index < len(options):
        return str(options[index])
    if isinstance(options, dict):
        return canonical_answer(options.get(normalized_answer))
    choice_key = f"choice_{normalized_answer}"
    if choice_key in row:
        return canonical_answer(row[choice_key])
    return None


def normalize_answer(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\u4e00-\u9fff]+", " ", value.lower())).strip()


def benchmark_prompt(benchmark: BenchmarkSpec, row: dict[str, Any]) -> str:
    question = first_present_raw(row, ("question", "query", "text")) or ""
    options = first_present_raw(row, ("options", "choices")) or ""
    context = first_present_raw(row, ("context", "document", "passage")) or ""
    context = compact_preview(context, 6000)
    media_note = "Use the attached image evidence." if any(is_pil_image(value) for value in row.values()) else ""
    if benchmark.name == "OCRBench":
        return f"""Use /no_think mode. Return compact JSON only.

Benchmark: OCRBench
Task type: image text recognition
Metric: exact_or_contains_accuracy
Use the attached image evidence.

Question:
{question}

Read the exact text in the image. For handwritten English words, return the standard spelling with the same letters.

Return exactly this JSON shape:
{{"answer":"<recognized text>"}}
"""
    return f"""Use /no_think mode. Return compact JSON only.

Benchmark: {benchmark.name}
Task type: {benchmark.task_type}
Metric: {benchmark.metric}
{media_note}

Question:
{question}

Options:
{options}

Context:
{context}

Return exactly this JSON shape:
{{"answer":"<prediction>"}}
"""


def extract_answer(text: str) -> str:
    stripped = text.strip()
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        payload = None
        if start >= 0 and end > start:
            try:
                payload = json.loads(stripped[start : end + 1])
            except json.JSONDecodeError:
                payload = None
    if isinstance(payload, dict) and payload.get("answer") is not None:
        return str(payload["answer"]).strip()
    return compact_preview(stripped, 500)


def canonical_answer(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        return " | ".join(str(item) for item in value)
    return str(value)


def first_present_raw(row: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = row.get(key)
        if value is not None:
            return value
    return None


def normalize_sample(row: dict[str, Any], output_root: Path) -> tuple[dict[str, Any], list[str]]:
    media_artifacts: list[str] = []
    normalized: dict[str, Any] = {}
    for key, value in row.items():
        normalized_value, artifact = normalize_sample_value(key, value, output_root)
        normalized[key] = normalized_value
        if artifact:
            media_artifacts.append(artifact)
    return normalized, media_artifacts


def prepare_prediction_media(benchmark: BenchmarkSpec, media_artifacts: list[str]) -> list[str]:
    if benchmark.name != "OCRBench":
        return media_artifacts
    return [str(enhance_ocr_benchmark_image(Path(path))) for path in media_artifacts]


def enhance_ocr_benchmark_image(path: Path) -> Path:
    from PIL import Image, ImageOps

    image = Image.open(path).convert("RGB")
    max_side = max(image.size)
    scale = max(1, min(10, math.ceil(768 / max_side)))
    if scale > 1:
        image = image.resize((image.width * scale, image.height * scale), Image.Resampling.BICUBIC)
    border = max(8, scale * 2)
    image = ImageOps.expand(image, border=border, fill="white")
    target = path.with_name(f"{path.stem}_ocr_x{scale}{path.suffix}")
    image.save(target)
    return target


def normalize_sample_value(key: str, value: Any, output_root: Path) -> tuple[Any, str | None]:
    if is_pil_image(value):
        digest = image_sha256(value)
        artifact = output_root / f"{slugify(key)}_{digest[:12]}.png"
        value.save(artifact)
        return (
            {
                "type": "image",
                "mode": getattr(value, "mode", None),
                "size": list(getattr(value, "size", ())),
                "sha256": digest,
            },
            str(artifact),
        )
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value, None
    if isinstance(value, (list, tuple)):
        return [normalize_sample_value(f"{key}_{index}", item, output_root)[0] for index, item in enumerate(value)], None
    if isinstance(value, dict):
        return {str(item_key): normalize_sample_value(str(item_key), item_value, output_root)[0] for item_key, item_value in value.items()}, None
    return str(value), None


def is_pil_image(value: Any) -> bool:
    return hasattr(value, "save") and hasattr(value, "mode") and hasattr(value, "size")


def image_sha256(image: Any) -> str:
    import io

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return sha256_bytes(buffer.getvalue())


def sample_identifier(row: dict[str, Any]) -> str | None:
    for key in ("id", "_id", "question_id", "query-id", "text_id", "video_id", "corpus-id"):
        value = row.get(key)
        if value is not None:
            return str(value)
    return None


def first_present(row: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = row.get(key)
        if value is not None:
            return compact_preview(value)
    return None


def compact_preview(value: Any, limit: int = 240) -> str:
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text[:limit]


def sha256_json(value: dict[str, Any]) -> str:
    return sha256_bytes(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8"))


def sha256_bytes(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


def slugify(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "-", value).strip("-").lower() or "item"
