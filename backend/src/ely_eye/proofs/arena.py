"""Draw the HashHop puzzles and read the model's answer back out of them."""

from __future__ import annotations

import hashlib
import json
import random
import re
from pathlib import Path
from typing import Any, Literal

from PIL import Image, ImageDraw, ImageFont

# The four arena positions a model may answer with. Naming them once keeps the puzzle, the parser,
# and the scoring keyed on the same values instead of four spellings in three files.
SlotName = Literal["top-left", "top-right", "bottom-left", "bottom-right"]
SLOTS: tuple[SlotName, ...] = ("top-left", "top-right", "bottom-left", "bottom-right")

ID_LINE_CHARS = 8
CANVAS_BACKGROUND = (8, 10, 14)


def render_visual_hash(item_id: str, path: Path, tile_size: int) -> None:
    """Print the id on the tile, over a pattern derived from the same id.

    A pattern alone is not a puzzle: nothing maps a random texture back to a hex id, so the
    only way to answer was the ink the renderer painted on the answer. The id is now legible,
    which makes the task look, match, and answer.
    """
    seed = int(hashlib.sha256(item_id.encode("utf-8")).hexdigest()[:16], 16)
    rng = random.Random(seed)
    image = Image.new("RGB", (tile_size, tile_size), color=_noise_color(rng))
    draw = ImageDraw.Draw(image)
    for _ in range(96):
        x0 = rng.randrange(tile_size)
        y0 = rng.randrange(tile_size)
        x1 = min(tile_size, x0 + rng.randrange(4, tile_size // 3))
        y1 = min(tile_size, y0 + rng.randrange(4, tile_size // 3))
        color = _noise_color(rng)
        if rng.random() < 0.5:
            draw.rectangle([x0, y0, x1, y1], fill=color)
        else:
            draw.ellipse([x0, y0, x1, y1], fill=color)
    _draw_id(draw, item_id, tile_size)
    image.save(path)


def _noise_color(rng: random.Random) -> tuple[int, int, int]:
    return (rng.randrange(256), rng.randrange(256), rng.randrange(256))


def _draw_id(draw: ImageDraw.ImageDraw, item_id: str, tile_size: int) -> None:
    font = ImageFont.load_default(size=max(12, tile_size // 8))
    plate = (
        int(tile_size * 0.05),
        int(tile_size * 0.16),
        int(tile_size * 0.95),
        int(tile_size * 0.88),
    )
    draw.rectangle(plate, fill=(255, 255, 255))
    lines = [item_id[start : start + ID_LINE_CHARS] for start in range(0, len(item_id), ID_LINE_CHARS)]
    line_height = font.getbbox("AbgJ")[3]
    block_top = (plate[1] + plate[3]) / 2 - (len(lines) * line_height) / 2
    for index, line in enumerate(lines):
        box = font.getbbox(line)
        left = (plate[0] + plate[2]) / 2 - (box[2] - box[0]) / 2
        draw.text((left, block_top + index * line_height), line, fill=(12, 14, 18), font=font)


def render_visual_hash_arena(
    source_path: Path, slot_paths: dict[str, Path], output_path: Path
) -> None:
    """Place the source and the candidates. Nothing marks which candidate is the answer."""
    tile = 160
    canvas = Image.new("RGB", (920, 560), color=CANVAS_BACKGROUND)
    draw = ImageDraw.Draw(canvas)
    source_box = (72, 200, 72 + tile, 200 + tile)
    slot_boxes = _slot_boxes(520, 704, 76, 324, tile)
    paste_visual_hash_tile(canvas, source_path, source_box)
    draw.rectangle(source_box, outline=(255, 78, 220), width=8)
    for slot, box in slot_boxes.items():
        paste_visual_hash_tile(canvas, slot_paths[slot], box)
        draw.rectangle(box, outline=(180, 190, 205), width=5)
    _save(canvas, output_path)


def render_visual_hash_two_hop_arena(
    source_path: Path,
    intermediate_slot_paths: dict[str, Path],
    target_slot_paths: dict[str, Path],
    output_path: Path,
) -> None:
    """Two grids of candidates, no arrow and no ring: the chain has to be read, not seen."""
    tile = 136
    canvas = Image.new("RGB", (1180, 720), color=CANVAS_BACKGROUND)
    draw = ImageDraw.Draw(canvas)
    source_box = (64, 292, 64 + tile, 292 + tile)
    intermediate_boxes = _slot_boxes(424, 584, 104, 480, tile)
    target_boxes = _slot_boxes(864, 1024, 104, 480, tile)
    paste_visual_hash_tile(canvas, source_path, source_box)
    draw.rectangle(source_box, outline=(255, 78, 220), width=7)
    for grid, boxes, outline in (
        (intermediate_slot_paths, intermediate_boxes, (140, 215, 255)),
        (target_slot_paths, target_boxes, (255, 196, 92)),
    ):
        for slot, box in boxes.items():
            paste_visual_hash_tile(canvas, grid[slot], box)
            draw.rectangle(box, outline=outline, width=5)
    _save(canvas, output_path)


def _slot_boxes(
    left_x: int, right_x: int, top_y: int, bottom_y: int, tile: int
) -> dict[str, tuple[int, int, int, int]]:
    return {
        "top-left": (left_x, top_y, left_x + tile, top_y + tile),
        "top-right": (right_x, top_y, right_x + tile, top_y + tile),
        "bottom-left": (left_x, bottom_y, left_x + tile, bottom_y + tile),
        "bottom-right": (right_x, bottom_y, right_x + tile, bottom_y + tile),
    }


def _save(canvas: Image.Image, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path)


def paste_visual_hash_tile(canvas: Image.Image, path: Path, box: tuple[int, int, int, int]) -> None:
    tile = Image.open(path).convert("RGB").resize((box[2] - box[0], box[3] - box[1]), Image.Resampling.LANCZOS)
    canvas.paste(tile, box[:2])


def extract_visual_target_slot(text: str) -> SlotName | None:
    stripped = text.strip()
    payload: dict[str, Any] | None
    try:
        parsed = json.loads(stripped)
        payload = parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        payload = extract_json_object(stripped)
    if isinstance(payload, dict):
        for key in ("target_slot", "final_slot", "slot", "answer"):
            value = payload.get(key)
            if isinstance(value, str):
                slot = normalize_visual_slot(value)
                if slot:
                    return slot
    return normalize_visual_slot(stripped)


def extract_hashhop_target(text: str) -> str | None:
    """Read the id the model answered with, from JSON or from loose prose."""
    stripped = text.strip()
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        payload = extract_json_object(stripped)
    if isinstance(payload, dict):
        for key in ("answer", "target", "target_id", "final_target_id"):
            value = payload.get(key)
            if isinstance(value, str):
                candidate = normalize_hash_id(value)
                if candidate:
                    return candidate
    match = re.search(r"\b[a-fA-F0-9]{32}\b", stripped)
    return match.group(0).lower() if match else None


def normalize_hash_id(value: str) -> str | None:
    match = re.search(r"\b[a-fA-F0-9]{32}\b", value)
    return match.group(0).lower() if match else None


def extract_visual_intermediate_slot(text: str) -> SlotName | None:
    stripped = text.strip()
    try:
        parsed = json.loads(stripped)
        payload = parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        payload = extract_json_object(stripped)
    if isinstance(payload, dict):
        for key in ("intermediate_slot", "middle_slot", "first_hop_slot"):
            value = payload.get(key)
            if isinstance(value, str):
                slot = normalize_visual_slot(value)
                if slot:
                    return slot
    return None


def extract_json_object(text: str) -> dict[str, Any] | None:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        payload = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def normalize_visual_slot(value: str) -> SlotName | None:
    normalized = re.sub(r"[^a-z]+", "-", value.lower()).strip("-")
    aliases: dict[str, SlotName] = {
        "top-left": "top-left",
        "upper-left": "top-left",
        "left-top": "top-left",
        "top-right": "top-right",
        "upper-right": "top-right",
        "right-top": "top-right",
        "bottom-left": "bottom-left",
        "lower-left": "bottom-left",
        "left-bottom": "bottom-left",
        "bottom-right": "bottom-right",
        "lower-right": "bottom-right",
        "right-bottom": "bottom-right",
    }
    if normalized in aliases:
        return aliases[normalized]
    for alias, slot in aliases.items():
        if re.search(rf"\b{re.escape(alias)}\b", normalized):
            return slot
    return None
