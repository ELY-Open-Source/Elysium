"""What a picture says when it has no words on it.

OCR reads letters; it cannot say what a sunset, a shopping cart, or a warning triangle is. A
vision-language model can, and its sentence becomes the atom's text so ordinary word search can
reach the picture too. The model is a multi-gigabyte download, so this path is written, gated on
a snapshot, and reported as deferred until somebody fetches one: an unrun capability is a plan,
not a result.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import Settings, get_settings

PROMPT = "Describe what is in this image in one or two sentences. Name the objects and any visible text."
DOWNLOAD_HINT = "fetch a Qwen-VL snapshot and set ELY_EYE_VLM_MODEL_DIR to the directory holding it"
DEFERRED = "deferred: no vision-language model snapshot"


class VisionDescriber:
    """One lazily loaded vision model; `describe_or_none` is the path ingestion takes."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._model: Any | None = None
        self._processor: Any | None = None

    def model_dir(self) -> Path | None:
        model_dir = self.settings.vlm_model_dir
        if model_dir is None or not Path(model_dir).is_dir():
            return None
        return Path(model_dir)

    def available(self) -> bool:
        return self.model_dir() is not None

    def describe(self, path: Path) -> str:
        """Caption one picture; a missing snapshot is a setup error, not an empty answer."""
        model_dir = self.model_dir()
        if model_dir is None:
            raise SystemExit(f"{path}: image description needs a vision-language model; {DOWNLOAD_HINT}")
        if not path.is_file():
            raise ValueError(f"{path}: no picture to describe")
        return self._caption(path, model_dir)

    def describe_or_none(self, path: Path) -> str | None:
        """Caption if this machine can, otherwise say nothing and let the caller record why.

        A model failure is raised, not swallowed: ingestion decides whether a broken vision
        model kills the ingest or becomes a note on the atom, and it is the one that knows.
        """
        if not self.available():
            return None
        return self._caption(path, self.model_dir() or Path())

    def _caption(self, path: Path, model_dir: Path) -> str:
        processor, model = self._load(model_dir)
        import torch
        from PIL import Image

        with Image.open(path) as picture:
            inputs = processor(images=picture.convert("RGB"), text=PROMPT, return_tensors="pt").to(
                model.device, torch.float16
            )
            generated = model.generate(**inputs, max_new_tokens=self.settings.vlm_max_new_tokens, do_sample=False)
        trimmed = generated[:, inputs["input_ids"].shape[1] :]
        text = processor.batch_decode(trimmed, skip_special_tokens=True)[0].strip()
        if not text:
            raise ValueError(f"{path}: the vision model answered with nothing")
        return text

    def _load(self, model_dir: Path) -> tuple[Any, Any]:
        """Load once, and hand back the pair so the caller never reads a half-built attribute."""
        processor, model = self._processor, self._model
        if processor is None or model is None:
            import torch
            from transformers import AutoModelForImageTextToText, AutoProcessor

            processor = AutoProcessor.from_pretrained(str(model_dir))
            model = AutoModelForImageTextToText.from_pretrained(
                str(model_dir), torch_dtype=torch.float16, device_map="auto"
            )
            model.eval()
            self._processor, self._model = processor, model
        return processor, model
