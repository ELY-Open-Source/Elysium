"""What a picture shows, in words a search can match.

OCR reads letters; it cannot say that a screen holds a QR-code button, that a frame shows four
performers, or that a chart's blue series falls. A vision-language model can, and its sentences
join the atom's text so ordinary word search reaches the picture. The model is served, not loaded
here: a 9B model needs a GPU process of its own (`scripts/launch-vllm-live.sh`), and this module
talks to it over the OpenAI-compatible API the runtime already uses.
"""

from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

from .config import Settings, get_settings
from .db import Database
from .schemas import EvidenceAtom
from .storage import ObjectStore, token_equivalent
from .vector_index import VectorIndex

PROMPT = (
    "Describe this image so it can be found by search. Name the main objects, people and how many, "
    "actions, colours, any chart (axes, series, colours, trend), and for a screen the visible buttons "
    "and icons by what they do. Plain sentences, no preamble."
)
SETUP_HINT = "serve a vision-language model (scripts/launch-vllm-live.sh) and set ELYSIUM_VLM_BASE_URL to its /v1 URL"
DEFERRED = "deferred: no vision-language model is served"
DESCRIBED = "vlm"
BATCH = 64


class VisionDescriber:
    """A client for the served vision model; `describe_or_none` is the path ingestion takes."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def base_url(self) -> str | None:
        return self.settings.vlm_base_url

    def available(self) -> bool:
        return self.base_url() is not None

    def answers(self) -> bool:
        """Whether the configured model is up; a status probe, so it waits two seconds at most."""
        try:
            return httpx.get(f"{self.base_url()}/models", timeout=2.0).status_code == 200
        except httpx.HTTPError:
            return False

    def describe(self, path: Path) -> str:
        """Describe one picture; no served model is a setup error, not an empty answer."""
        if self.base_url() is None:
            raise SystemExit(f"{path}: image description needs a served vision-language model; {SETUP_HINT}")
        return self._describe(path)

    def describe_or_none(self, path: Path) -> str | None:
        """Describe if a model is served, otherwise say nothing and let the caller record why.

        A model failure is raised, not swallowed: ingestion decides whether a broken vision
        model kills the ingest or becomes a note on the atom, and it is the one that knows.
        """
        if not self.available():
            return None
        return self._describe(path)

    def _describe(self, path: Path) -> str:
        if not path.is_file():
            raise ValueError(f"{path}: no picture to describe")
        encoded = base64.b64encode(path.read_bytes()).decode()
        payload = {
            "model": self.settings.model_id,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:image/{path.suffix.lstrip('.')};base64,{encoded}"}},
                        {"type": "text", "text": PROMPT},
                    ],
                }
            ],
            "max_tokens": self.settings.vlm_max_new_tokens,
            "temperature": 0,
            # Describing needs no reasoning; thinking first only costs tokens before the answer.
            "chat_template_kwargs": {"enable_thinking": False},
        }
        try:
            response = httpx.post(f"{self.base_url()}/chat/completions", json=payload, timeout=None)
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise RuntimeError(f"{path}: the vision model at {self.base_url()} failed: {error}") from error
        text = str(response.json()["choices"][0]["message"]["content"] or "").strip()
        if not text:
            raise ValueError(f"{path}: the vision model answered with nothing")
        return text


def with_description(atom: EvidenceAtom, description: str) -> EvidenceAtom:
    """The printed words stay first; the model's sentences follow, and the atom says a model wrote them."""
    text = f"{atom.text}\n{description}" if atom.text.strip() else description
    return atom.model_copy(
        update={
            "text": text,
            "token_equivalent": atom.token_equivalent - token_equivalent(atom.text) + token_equivalent(text),
            "trust": atom.trust.model_copy(update={"model": 0.6}),
            "metadata": {**atom.metadata, "caption": DESCRIBED},
        }
    )


def describe_pictures(settings: Settings, database: Database, workers: int) -> dict[str, int]:
    """Describe every picture a store already holds that no model has described yet.

    A store ingested before a vision model was served keeps OCR text only; this brings it to
    what ingest would write today. It resumes: a described atom says so and is skipped.
    """
    describer = VisionDescriber(settings)
    if not describer.available():
        raise SystemExit(f"nothing can describe the pictures; {SETUP_HINT}")
    if workers <= 0:
        raise SystemExit(f"describing needs at least one worker, got {workers}")
    objects = ObjectStore(settings)
    vectors = VectorIndex(settings, database)
    pending = [atom for atom in _pictures(database) if atom.metadata.get("caption") != DESCRIBED]
    described = 0
    with ThreadPoolExecutor(workers) as pool:
        for start in range(0, len(pending), BATCH):
            batch = pending[start : start + BATCH]
            paths = [objects.resolve(str(atom.image_ref)) for atom in batch]
            texts = list(pool.map(describer.describe, paths))
            database.upsert_atoms([with_description(atom, text) for atom, text in zip(batch, texts, strict=True)])
            vectors.sync_atoms([atom.atom_id for atom in batch])
            described += len(batch)
            print(f"described {described}/{len(pending)}", flush=True)
    return {"pending": len(pending), "described": described}


def _pictures(database: Database) -> list[EvidenceAtom]:
    with database.connect() as connection:
        ids = [
            str(row["atom_id"])
            for row in connection.execute(
                "SELECT atom_id FROM atoms WHERE modality IN (SELECT value FROM json_each(?)) "
                "AND image_ref IS NOT NULL AND image_ref != '' ORDER BY atom_id",
                ('["image", "ui_screenshot", "video_frame"]',),
            )
        ]
    return database.get_atoms(ids)
