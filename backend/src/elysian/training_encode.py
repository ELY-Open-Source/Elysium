"""Turn a training sample into model inputs: chat text, images, pooled embeddings."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .training_common import SYSTEM_PROMPT, TrainingSample, section_by_title, sha256_file


def encode_training_sample(
    sample: TrainingSample,
    processor: Any,
    device: Any,
    max_length: int,
) -> dict[str, Any]:
    messages = messages_for_sample(sample, include_answer=True)
    prompt_messages = messages_for_sample(sample, include_answer=False)
    image_inputs, video_inputs = vision_inputs(messages)
    text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=False)
    prompt_text = processor.apply_chat_template(
        prompt_messages,
        tokenize=False,
        add_generation_prompt=True,
        enable_thinking=False,
    )
    inputs = processor(
        text=[text],
        images=image_inputs,
        videos=video_inputs,
        return_tensors="pt",
    )
    prompt_inputs = processor(
        text=[prompt_text],
        images=image_inputs,
        videos=video_inputs,
        return_tensors="pt",
    )
    labels = inputs["input_ids"].clone()
    prompt_length = min(int(prompt_inputs["input_ids"].shape[-1]), int(labels.shape[-1]))
    labels[:, :prompt_length] = -100
    pad_token_id = getattr(processor, "tokenizer", processor).pad_token_id
    if pad_token_id is not None:
        labels[labels == pad_token_id] = -100
    if int((labels != -100).sum().item()) == 0:
        raise ValueError(f"Sample {sample.id} produced no trainable tokens")
    inputs["labels"] = labels
    if int(inputs["input_ids"].shape[-1]) > max_length:
        for key in ("input_ids", "attention_mask", "labels"):
            if key in inputs:
                inputs[key] = inputs[key][:, -max_length:]
    return {key: value.to(device) if hasattr(value, "to") else value for key, value in inputs.items()}

def encode_retrieval_batch(
    texts: list[str],
    processor: Any,
    device: Any,
    max_length: int,
) -> dict[str, Any]:
    tokenizer = getattr(processor, "tokenizer", processor)
    inputs = tokenizer(
        texts,
        padding=True,
        truncation=True,
        max_length=max_length,
        return_tensors="pt",
    )
    return {key: value.to(device) if hasattr(value, "to") else value for key, value in inputs.items()}

def pool_embeddings(outputs: Any, attention_mask: Any) -> Any:
    import torch.nn.functional as F

    hidden = outputs.last_hidden_state
    mask = attention_mask.unsqueeze(-1).to(hidden.dtype)
    pooled = (hidden * mask).sum(dim=1) / mask.sum(dim=1).clamp_min(1.0)
    return F.normalize(pooled, dim=-1)

def messages_for_sample(sample: TrainingSample, include_answer: bool) -> list[dict[str, Any]]:
    user_content: list[dict[str, Any]] = []
    for item in sample.inputs:
        item_type = item.get("type")
        if item_type in {"image", "pdf_page", "ui_screenshot"} and item.get("path"):
            path = str(item["path"])
            if path.startswith("object://"):
                user_content.append({"type": "text", "text": f"Image object reference: {path}"})
            else:
                image_part: dict[str, Any] = {"type": "image", "image": path}
                for key in ("min_pixels", "max_pixels"):
                    if key in item:
                        image_part[key] = item[key]
                user_content.append(image_part)
        elif item_type == "text" and item.get("text"):
            user_content.append({"type": "text", "text": str(item["text"])})
        else:
            user_content.append({"type": "text", "text": json.dumps(item, ensure_ascii=False)})
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
    if include_answer:
        messages.append(
            {
                "role": "assistant",
                "content": json.dumps(sample.output, ensure_ascii=False, separators=(",", ":")),
            }
        )
    return messages

def vision_inputs(messages: list[dict[str, Any]]) -> tuple[list[Any] | None, list[Any] | None]:
    has_media = any(
        isinstance(content, list)
        and any(part.get("type") in {"image", "video"} for part in content if isinstance(part, dict))
        for content in (message.get("content") for message in messages)
    )
    if not has_media:
        return None, None
    from qwen_vl_utils import process_vision_info

    images, videos, *_ = process_vision_info(messages)
    return images, videos

def prepare_training_image(source: Path, media_dir: Path, max_side: int = 896) -> Path:
    from PIL import Image

    image = Image.open(source).convert("RGB")
    image.thumbnail((max_side, max_side))
    target = media_dir / f"{source.stem}_{sha256_file(source)[:10]}.png"
    image.save(target)
    return target

def render_prd_training_card(text: str, atom_id: str, target: Path) -> Path:
    from PIL import Image, ImageDraw, ImageFont

    target.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (1024, 768), "#f7f5ef")
    draw = ImageDraw.Draw(image)
    font_path = Path("C:/Windows/Fonts/msyh.ttc")
    title_font = ImageFont.truetype(str(font_path), 34) if font_path.exists() else ImageFont.load_default()
    body_font = ImageFont.truetype(str(font_path), 21) if font_path.exists() else ImageFont.load_default()
    small_font = ImageFont.truetype(str(font_path), 18) if font_path.exists() else ImageFont.load_default()
    draw.rectangle((28, 28, 996, 740), outline="#1f5f4a", width=3)
    draw.text((52, 48), "Elysian PRD Training Card", fill="#09201b", font=title_font)
    draw.text((52, 100), f"Evidence Atom: {atom_id}", fill="#1f5f4a", font=small_font)
    source = (
        section_by_title(text, "12.1 训练目标")
        + "\n"
        + section_by_title(text, "12.2 训练策略")
        + "\n"
        + section_by_title(text, "12.3 训练数据结构")
    )
    y = 148
    for line in wrap_text(compact_text(source, 1500), width=42):
        draw.text((52, y), line, fill="#09201b", font=body_font)
        y += 31
        if y > 700:
            break
    image.save(target)
    return target

def wrap_text(text: str, width: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for char in text:
        current += char
        if len(current) >= width or char == "\n":
            lines.append(current.strip())
            current = ""
    if current.strip():
        lines.append(current.strip())
    return lines

def compact_text(text: str, limit: int) -> str:
    compacted = re.sub(r"\s+", " ", text).strip()
    if len(compacted) <= limit:
        return compacted
    return compacted[: limit - 3].rstrip() + "..."
