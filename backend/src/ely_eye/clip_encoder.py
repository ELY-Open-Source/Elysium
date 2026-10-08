"""Image and text encoding for cross-modal retrieval, over one small ONNX graph.

Chinese-CLIP ViT-B/16 in fp16 (377 MB) keeps bilingual text and images in one vector
space, so a screenshot can be found by a picture or by a sentence. The graph is the
fused contrastive model: every call needs both towers' inputs, so the unused side is
fed a placeholder row.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

IMAGE_SIZE = 224
TEXT_MAX_LENGTH = 52
IMAGE_MEAN = (0.48145466, 0.45782750, 0.40821073)
IMAGE_STD = (0.26862954, 0.26130258, 0.27577711)
DOWNLOAD_HINT = (
    "huggingface-cli download Xenova/chinese-clip-vit-base-patch16 "
    "--include 'onnx/model_fp16.onnx' 'tokenizer*' 'config.json' --local-dir <dir>"
)


def preprocess_image(image: Image.Image) -> np.ndarray:
    """Turn a PIL image into the (3, 224, 224) float32 tensor the graph expects.

    The reference processor resizes to a square and normalizes with CLIP constants;
    doing it here keeps torchvision out of the dependency list.
    """
    rgb = image.convert("RGB").resize((IMAGE_SIZE, IMAGE_SIZE), Image.Resampling.BICUBIC)
    array = np.asarray(rgb, dtype=np.float32) / 255.0
    mean = np.array(IMAGE_MEAN, dtype=np.float32)
    std = np.array(IMAGE_STD, dtype=np.float32)
    return ((array - mean) / std).transpose(2, 0, 1)


class ClipEncoder:
    """One ONNX session, both towers, batched image encoding."""

    def __init__(self, model_dir: Path) -> None:
        self.model_dir = Path(model_dir)
        self.onnx_path = self.model_dir / "onnx" / "model_fp16.onnx"
        if not self.onnx_path.exists():
            raise SystemExit(
                f"{self.onnx_path} is not a Chinese-CLIP export; fetch the fp16 graph: {DOWNLOAD_HINT}"
            )
        self._session: Any | None = None
        self._tokenizer: Any | None = None
        self._placeholder_text: dict[str, np.ndarray] | None = None
        self._placeholder_image: np.ndarray | None = None

    @property
    def session(self) -> Any:
        if self._session is None:
            import onnxruntime as ort

            self._session = ort.InferenceSession(str(self.onnx_path), providers=["CPUExecutionProvider"])
        return self._session

    @property
    def tokenizer(self) -> Any:
        if self._tokenizer is None:
            from transformers import BertTokenizer

            # The export is BERT-style (vocab.txt, [CLS]=101); transformers 5 unified the fast and
            # slow tokenizers, so the name the CLIP docs use is an alias for this one.
            self._tokenizer = BertTokenizer.from_pretrained(str(self.model_dir))
        return self._tokenizer

    def encode_images(self, images: list[Image.Image], batch_size: int = 8) -> np.ndarray:
        if not images:
            return np.zeros((0, 512), dtype=np.float32)
        rows: list[np.ndarray] = []
        for start in range(0, len(images), batch_size):
            chunk = images[start : start + batch_size]
            pixels = np.stack([preprocess_image(image) for image in chunk])
            rows.append(self._run("image_embeds", pixels, self._text_feed(1))[0])
        return np.asarray(np.concatenate(rows), dtype=np.float32)

    def encode_texts(self, texts: list[str], batch_size: int = 16) -> np.ndarray:
        if not texts:
            return np.zeros((0, 512), dtype=np.float32)
        rows: list[np.ndarray] = []
        for start in range(0, len(texts), batch_size):
            chunk = texts[start : start + batch_size]
            feed = self._text_feed(len(chunk), chunk)
            rows.append(self._run("text_embeds", self._image_feed(len(chunk)), feed)[0])
        return np.asarray(np.concatenate(rows), dtype=np.float32)

    def _run(self, output: str, pixels: np.ndarray, text: dict[str, np.ndarray]) -> list[np.ndarray]:
        feed = {"pixel_values": pixels.astype(np.float32), **text}
        return self.session.run([output], feed)

    def _text_feed(self, batch: int, texts: list[str] | None = None) -> dict[str, np.ndarray]:
        if texts is None:
            if self._placeholder_text is None:
                self._placeholder_text = self._tokenize(["placeholder"])
            return self._placeholder_text
        return self._tokenize(texts)

    def _image_feed(self, batch: int) -> np.ndarray:
        if self._placeholder_image is None:
            self._placeholder_image = np.zeros((1, 3, IMAGE_SIZE, IMAGE_SIZE), dtype=np.float32)
        return np.repeat(self._placeholder_image, batch, axis=0)

    def _tokenize(self, texts: list[str]) -> dict[str, np.ndarray]:
        encoded = self.tokenizer(
            texts,
            padding="max_length",
            truncation=True,
            max_length=TEXT_MAX_LENGTH,
            return_tensors="np",
        )
        return {
            "input_ids": encoded["input_ids"].astype(np.int64),
            "attention_mask": encoded["attention_mask"].astype(np.int64),
        }
