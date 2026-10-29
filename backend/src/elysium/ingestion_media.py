"""Pictures, PDFs, video and speech: the readers that need a model or a decoder."""

from __future__ import annotations

import tempfile
from abc import ABC, abstractmethod
from pathlib import Path

import cv2
import pymupdf as fitz

from .asr import DEFERRED as SPEECH_DEFERRED
from .asr import SpeechSegment, SpeechTranscriber
from .config import Settings
from .db import Database
from .describe import DEFERRED, VisionDescriber, with_description
from .ingestion_common import (
    IngestBatch,
    image_metadata,
    image_size,
)
from .ocr import read_text_from_image
from .schemas import (
    EvidenceAtom,
    LayoutBox,
    Modality,
    SourceRecord,
    TrustScores,
)
from .storage import (
    ObjectStore,
    token_equivalent,
    visual_token_equivalent,
)


def _page_text(page: fitz.Page) -> str:
    """Plain text of one page; the type stubs widen get_text's answer for the other modes."""
    extracted = page.get_text("text")
    if isinstance(extracted, str):
        return extracted.strip()
    return "\n".join(str(part) for part in extracted).strip()


class MediaIngest(ABC):
    """Readers for pictures, PDFs, video and speech.

    A mixin: the host supplies identity and storage, this supplies the senses. The requirements
    are abstract so a half-wired host fails at construction instead of returning None.
    """

    settings: Settings
    db: Database
    objects: ObjectStore
    describer: VisionDescriber
    transcriber: SpeechTranscriber

    @abstractmethod
    def _source_record(
        self,
        path: Path,
        kind: str,
        metadata: dict[str, object] | None = None,
    ) -> SourceRecord:
        """Where a file's source row comes from; the host decides identity."""

    def _ingest_image(self, path: Path) -> IngestBatch:
        source = self._source_record(path, self._image_kind(path), metadata=image_metadata(path))
        image_ref = self.objects.put_file(path, "images")
        ocr = read_text_from_image(path)
        text = ocr.text
        width, height = image_size(path)
        atom = EvidenceAtom(
            atom_id=f"{source.source_id}:image",
            modality=Modality.ui_screenshot if source.kind == "ui_screenshot" else Modality.image,
            source_id=source.source_id,
            source=str(path),
            text=text,
            image_ref=image_ref,
            layout=LayoutBox(x=0, y=0, w=width, h=height),
            trust=TrustScores(parser=1.0, ocr=ocr.confidence, model=0.0),
            token_equivalent=token_equivalent(text) + visual_token_equivalent(width, height),
            metadata={"ocr_regions": ocr.regions, **image_metadata(path)},
        )
        return IngestBatch(sources=[source], atoms=[self._described(atom, path)])

    def _described(self, atom: EvidenceAtom, path: Path) -> EvidenceAtom:
        """Printed words do not say what a picture shows, so every picture is described when a model is served."""
        try:
            description = self.describer.describe_or_none(path)
        except (OSError, RuntimeError, ValueError) as error:
            return atom.model_copy(update={"metadata": {**atom.metadata, "caption": f"failed: {error}"}})
        if description is None:
            return atom.model_copy(update={"metadata": {**atom.metadata, "caption": DEFERRED}})
        return with_description(atom, description)

    def _ingest_pdf(self, path: Path) -> IngestBatch:
        source = self._source_record(path, "pdf")
        atoms: list[EvidenceAtom] = []
        with fitz.open(path) as document:
            source.metadata["page_count"] = document.page_count
            for page_index in range(1, document.page_count + 1):
                page = document[page_index - 1]
                rect = page.rect
                text = _page_text(page)
                pixmap = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
                image_bytes = pixmap.tobytes("png")
                image_ref = self.objects.put_bytes(image_bytes, ".png", "pdf_pages")
                if not text:
                    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as temp_file:
                        temp_file.write(image_bytes)
                        temp_path = Path(temp_file.name)
                    try:
                        ocr = read_text_from_image(temp_path)
                        text = ocr.text
                        ocr_confidence = ocr.confidence
                    finally:
                        temp_path.unlink(missing_ok=True)
                else:
                    ocr_confidence = 0.0
                atoms.append(
                    EvidenceAtom(
                        atom_id=f"{source.source_id}:page:{page_index:05d}",
                        modality=Modality.pdf_page,
                        source_id=source.source_id,
                        source=f"{path}#page={page_index}",
                        text=text,
                        image_ref=image_ref,
                        layout=LayoutBox(x=0, y=0, w=float(rect.width), h=float(rect.height), page=page_index),
                        trust=TrustScores(parser=1.0, ocr=ocr_confidence, model=0.0),
                        token_equivalent=token_equivalent(text) + max(1, int(rect.width * rect.height) // 50_000),
                        metadata={"page": page_index, "width": rect.width, "height": rect.height},
                    )
                )
                atoms.extend(self._pdf_region_atoms(path, source.source_id, page_index, page))
        return IngestBatch(sources=[source], atoms=atoms)

    def _pdf_region_atoms(
        self, path: Path, source_id: str, page_index: int, page: fitz.Page
    ) -> list[EvidenceAtom]:
        regions: list[EvidenceAtom] = []
        blocks = page.get_text("blocks")
        for block_index, block in enumerate(blocks):
            if len(block) < 5:
                continue
            x0, y0, x1, y1, text = block[:5]
            text = str(text).strip()
            if not text:
                continue
            regions.append(
                EvidenceAtom(
                    atom_id=f"{source_id}:page:{page_index:05d}:region:{block_index:04d}",
                    modality=Modality.pdf_region,
                    source_id=source_id,
                    source=f"{path}#page={page_index}&region={block_index}",
                    text=text,
                    layout=LayoutBox(
                        x=float(x0),
                        y=float(y0),
                        w=float(x1) - float(x0),
                        h=float(y1) - float(y0),
                        page=page_index,
                    ),
                    trust=TrustScores(parser=1.0, ocr=0.0, model=0.0),
                    token_equivalent=token_equivalent(text),
                    metadata={"page": page_index, "block": block_index},
                )
            )
        return regions

    def _ingest_video(self, path: Path) -> IngestBatch:
        source = self._source_record(path, "video")
        capture = cv2.VideoCapture(str(path))
        if not capture.isOpened():
            raise RuntimeError(f"Cannot open video file: {path}")

        fps = capture.get(cv2.CAP_PROP_FPS)
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = frame_count / fps if fps > 0 else 0.0
        source.metadata.update({"fps": fps, "frame_count": frame_count, "duration_seconds": duration})

        atoms: list[EvidenceAtom] = []
        step = max(1, int(fps * self.settings.video_sample_seconds)) if fps > 0 else 1
        frame_index = 0
        while frame_index < frame_count:
            capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
            ok, frame = capture.read()
            if not ok:
                break
            second = frame_index / fps if fps > 0 else 0.0
            success, encoded = cv2.imencode(".png", frame)
            if not success:
                frame_index += step
                continue
            image_bytes = encoded.tobytes()
            image_ref = self.objects.put_bytes(image_bytes, ".png", "video_frames")
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as temp_file:
                temp_file.write(image_bytes)
                temp_path = Path(temp_file.name)
            try:
                ocr = read_text_from_image(temp_path)
                height, width = frame.shape[:2]
                frame_atom = EvidenceAtom(
                    atom_id=f"{source.source_id}:frame:{frame_index:08d}",
                    modality=Modality.video_frame,
                    source_id=source.source_id,
                    source=f"{path}#t={second:.3f}",
                    text=ocr.text,
                    image_ref=image_ref,
                    layout=LayoutBox(x=0, y=0, w=float(width), h=float(height), frame_second=second),
                    trust=TrustScores(parser=1.0, ocr=ocr.confidence, model=0.0),
                    token_equivalent=token_equivalent(ocr.text) + visual_token_equivalent(width, height),
                    metadata={"frame_index": frame_index, "second": second, "ocr_regions": ocr.regions},
                )
                atoms.append(self._described(frame_atom, temp_path))
            finally:
                temp_path.unlink(missing_ok=True)
            frame_index += step
        capture.release()
        segments, note = self._speech(path)
        speech_atoms = self._speech_atoms(source, path, segments)
        source.metadata["speech"] = note or f"{len(speech_atoms)} segments of speech"
        atoms.extend(speech_atoms)
        return IngestBatch(sources=[source], atoms=atoms)

    def _ingest_audio(self, path: Path) -> IngestBatch:
        source = self._source_record(path, "audio")
        segments, note = self._speech(path)
        atoms = self._speech_atoms(source, path, segments)
        source.metadata["speech"] = note or f"{len(atoms)} segments of speech"
        return IngestBatch(sources=[source], atoms=atoms)

    def _speech(self, path: Path) -> tuple[list[SpeechSegment], str | None]:
        """Speech is optional here: no snapshot defers, a broken model becomes a note, not a dead ingest."""
        if not self.transcriber.available():
            return [], SPEECH_DEFERRED
        try:
            return self.transcriber.transcribe(path), None
        except (OSError, RuntimeError, ValueError) as error:
            return [], f"failed: {error}"

    def _speech_atoms(self, source: SourceRecord, path: Path, segments: list[SpeechSegment]) -> list[EvidenceAtom]:
        atoms: list[EvidenceAtom] = []
        for segment in segments:
            if not segment.text:
                continue
            atoms.append(
                EvidenceAtom(
                    atom_id=f"{source.source_id}:speech:{int(segment.start * 1000):010d}",
                    modality=Modality.audio,
                    source_id=source.source_id,
                    source=f"{path}#t={segment.start:.3f}",
                    text=segment.text,
                    layout=LayoutBox(x=0.0, y=0.0, w=0.0, h=0.0, frame_second=segment.start),
                    trust=TrustScores(parser=0.0, ocr=0.0, model=segment.confidence),
                    token_equivalent=token_equivalent(segment.text),
                    metadata={
                        "start_seconds": segment.start,
                        "end_seconds": segment.end,
                        "words": [
                            {"word": word.word, "start": word.start, "end": word.end, "confidence": word.confidence}
                            for word in segment.words
                        ],
                    },
                )
            )
        return atoms

    def _image_kind(self, path: Path) -> str:
        name = path.name.lower()
        ui_markers = ("screenshot", "screen", "figma", "ui", "wireframe", "mockup")
        return "ui_screenshot" if any(marker in name for marker in ui_markers) else "image"

