"""Finding a picture by a picture, or by a sentence.

The encoder is a 361 MB ONNX graph, so these tests swap in a fake that maps a picture's
colour, or a query's number, to a one-hot vector. What is under test is the index contract:
which atoms get encoded, when the index is stale, when search asks the picture tower at all,
and what happens when the snapshot is missing.
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

import numpy as np
import pytest
from PIL import Image

from ely_eye.clip_encoder import ClipEncoder
from ely_eye.config import Settings
from ely_eye.db import Database
from ely_eye.memory import MemoryService
from ely_eye.retrieval import RetrievalService
from ely_eye.schemas import EvidenceAtom, Modality, SourceRecord, TrustScores
from ely_eye.storage import ObjectStore
from ely_eye.visual_index import VisualIndex, is_visual

DIM = 4


class FakeEncoder:
    """A picture is its top-left colour; a text query is its digits."""

    def __init__(self) -> None:
        self.image_calls = 0
        self.text_calls = 0

    def encode_images(self, images: list[Image.Image], batch_size: int = 8) -> np.ndarray:
        self.image_calls += 1
        return _one_hot([int(np.asarray(image.convert("RGB"))[0, 0, 0]) for image in images])

    def encode_texts(self, texts: list[str], batch_size: int = 16) -> np.ndarray:
        self.text_calls += 1
        return _one_hot([int(text) for text in texts])


def _one_hot(codes: list[int]) -> np.ndarray:
    matrix = np.zeros((len(codes), DIM), dtype=np.float32)
    for row, code in enumerate(codes):
        matrix[row, code % DIM] = 1.0
    return matrix


def _settings(tmp_path: Path, with_model: bool = True) -> Settings:
    model_dir = tmp_path / "clip"
    if with_model:
        (model_dir / "onnx").mkdir(parents=True, exist_ok=True)
        (model_dir / "onnx" / "model_fp16.onnx").write_bytes(b"graph")
    return Settings(home=tmp_path / "home", clip_model_dir=model_dir, default_holder="wife")


def _picture(tmp_path: Path, name: str, shade: int) -> Path:
    path = tmp_path / f"{name}.png"
    Image.new("RGB", (64, 64), (shade, 0, 0)).save(path)
    return path


def _source(source_id: str, path: str, mime: str) -> SourceRecord:
    return SourceRecord(source_id=source_id, path=path, kind="file", mime=mime, sha256=source_id, size_bytes=64)


def _image_atom(tmp_path: Path, settings: Settings, database: Database, name: str, shade: int) -> EvidenceAtom:
    """Store a picture the way ingestion does: bytes in the object store, atom pointing at them."""
    picture = _picture(tmp_path, name, shade)
    uri = ObjectStore(settings).put_file(picture, "images")
    database.upsert_sources([_source(name, str(picture), "image/png")])
    atom = EvidenceAtom(
        atom_id=f"{name}:image",
        modality=Modality.image,
        source_id=name,
        source=f"file://{name}",
        text="",
        image_ref=uri,
        trust=TrustScores(parser=1.0, ocr=0.0, model=0.0),
        token_equivalent=920,
        holder_id=settings.default_holder,
    )
    database.upsert_atoms([atom])
    return atom


def _attach(index: VisualIndex, encoder: FakeEncoder) -> FakeEncoder:
    index._encoder = cast(ClipEncoder, encoder)
    return encoder


def _index(tmp_path: Path, with_model: bool = True) -> tuple[VisualIndex, Settings, Database, FakeEncoder]:
    settings = _settings(tmp_path, with_model)
    database = Database(settings)
    index = VisualIndex(settings, database)
    return index, settings, database, _attach(index, FakeEncoder())


def test_a_text_atom_is_not_findable_by_picture() -> None:
    atom = EvidenceAtom(
        atom_id="t:1",
        modality=Modality.text,
        source_id="s",
        source="file://s",
        text="钥匙放在抽屉里",
        trust=TrustScores(parser=1.0, ocr=0.0, model=0.0),
        token_equivalent=6,
    )
    assert not is_visual(atom)


def test_only_images_whose_bytes_survive_are_encoded(tmp_path: Path) -> None:
    index, settings, database, _ = _index(tmp_path)
    _image_atom(tmp_path, settings, database, "keep", 1)
    dead = _image_atom(tmp_path, settings, database, "gone", 2)
    ObjectStore(settings).resolve(str(dead.image_ref)).unlink()

    kept = index.visual_atoms()

    assert [atom.atom_id for atom in kept] == ["keep:image"]


def test_a_sentence_finds_the_picture_it_describes(tmp_path: Path) -> None:
    index, settings, database, encoder = _index(tmp_path)
    for shade in (1, 2, 3):
        _image_atom(tmp_path, settings, database, f"pic{shade}", shade)
    index.build()

    ranked = index.search_text("2", top_k=3)

    assert ranked[0][0] == "pic2:image"
    assert ranked[0][1] == pytest.approx(1.0)
    assert encoder.text_calls == 1


def test_a_picture_finds_the_picture_it_looks_like(tmp_path: Path) -> None:
    index, settings, database, _ = _index(tmp_path)
    for shade in (1, 2, 3):
        _image_atom(tmp_path, settings, database, f"pic{shade}", shade)
    index.build()

    ranked = index.search_image(_picture(tmp_path, "query", 3), top_k=2)

    assert [atom_id for atom_id, _ in ranked] == ["pic3:image", "pic1:image"]


def test_the_index_is_stale_the_moment_a_picture_arrives(tmp_path: Path) -> None:
    index, settings, database, _ = _index(tmp_path)
    _image_atom(tmp_path, settings, database, "first", 1)
    index.build()
    assert index.is_current()

    _image_atom(tmp_path, settings, database, "second", 2)

    assert not index.is_current(), "a new picture must not be invisible to search"


def test_a_pool_limits_the_answer_without_rebuilding_the_index(tmp_path: Path) -> None:
    index, settings, database, _ = _index(tmp_path)
    for shade in (1, 2, 3):
        _image_atom(tmp_path, settings, database, f"pic{shade}", shade)
    index.build()

    ranked = index.search_text("3", top_k=3, restrict={"pic1:image", "pic3:image"})
    assert [atom_id for atom_id, _ in ranked] == ["pic3:image", "pic1:image"]

    outside = index.search_text("3", top_k=3, restrict={"pic1:image", "pic2:image"})
    assert "pic3:image" not in [atom_id for atom_id, _ in outside]


def test_forgetting_a_picture_voids_the_picture_index(tmp_path: Path) -> None:
    index, settings, database, _ = _index(tmp_path)
    atom = _image_atom(tmp_path, settings, database, "pic1", 1)
    index.build()
    assert index.load() is not None, "warm the copy this process holds"

    report = MemoryService(settings, database).forget(source_id=atom.source_id)

    assert report.vector_index_dropped
    assert not index.index_path.exists() and not index.map_path.exists()
    assert index.load() is None, "a forgotten picture must not keep answering from memory"


def test_a_missing_snapshot_is_named_rather_than_mumbled(tmp_path: Path) -> None:
    settings = _settings(tmp_path, with_model=False)

    index = VisualIndex(settings, Database(settings))

    assert not index.available()
    with pytest.raises(SystemExit, match="ELY_EYE_CLIP_MODEL_DIR"):
        index.encoder()


def test_a_map_that_disagrees_with_the_vectors_is_refused(tmp_path: Path) -> None:
    index, settings, database, _ = _index(tmp_path)
    _image_atom(tmp_path, settings, database, "only", 1)
    index.build()
    index.map_path.write_text('["only:image", "ghost:image"]', encoding="utf-8")

    with pytest.raises(ValueError, match="2 atoms for 1 vectors"):
        index.load()


def test_a_corrupt_map_names_the_file(tmp_path: Path) -> None:
    index, settings, database, _ = _index(tmp_path)
    _image_atom(tmp_path, settings, database, "only", 1)
    index.build()
    index.map_path.write_text("not json", encoding="utf-8")

    with pytest.raises(ValueError, match="visual index map is unreadable"):
        index.load()


def _search_service(encoder: FakeEncoder, settings: Settings, database: Database) -> RetrievalService:
    service = RetrievalService(settings, database)
    _attach(service.visual, encoder)
    return service


def test_words_that_come_up_short_let_the_picture_index_answer(tmp_path: Path) -> None:
    index, settings, database, encoder = _index(tmp_path)
    for shade in (1, 2, 3):
        _image_atom(tmp_path, settings, database, f"pic{shade}", shade)
    index.build()
    service = _search_service(encoder, settings, database)

    result = service.search("7", top_k=3)

    assert result.hits[0].atom.atom_id == "pic3:image"
    assert result.hits[0].visual_score == pytest.approx(1.0)
    assert encoder.text_calls == 1


def test_words_that_already_fill_the_page_do_not_pay_for_a_picture(tmp_path: Path) -> None:
    index, settings, database, encoder = _index(tmp_path)
    for shade in range(1, 9):
        _image_atom(tmp_path, settings, database, f"pic{shade}", shade)
        database.upsert_sources([_source(f"note{shade}", f"/tmp/note{shade}.md", "text/markdown")])
        database.upsert_atoms(
            [
                EvidenceAtom(
                    atom_id=f"note{shade}:text",
                    modality=Modality.text,
                    source_id=f"note{shade}",
                    source=f"file://note{shade}",
                    text="widget gadget sprocket",
                    trust=TrustScores(parser=1.0, ocr=0.0, model=0.0),
                    token_equivalent=3,
                    holder_id=settings.default_holder,
                )
            ]
        )
    index.build()
    service = _search_service(encoder, settings, database)

    result = service.search("widget gadget sprocket", top_k=2)

    assert encoder.text_calls == 0, "a page full of word matches does not need the encoder"
    assert all(hit.visual_score == 0.0 for hit in result.hits)


def test_an_image_query_uses_the_image_tower(tmp_path: Path) -> None:
    index, settings, database, encoder = _index(tmp_path)
    for shade in (1, 2):
        _image_atom(tmp_path, settings, database, f"pic{shade}", shade)
    index.build()
    service = _search_service(encoder, settings, database)

    picture_calls = encoder.image_calls

    result = service.search("", top_k=2, image=_picture(tmp_path, "q", 2))

    assert result.hits[0].atom.atom_id == "pic2:image"
    assert encoder.image_calls == picture_calls + 1, "the query picture goes through the image tower"
    assert encoder.text_calls == 0, "a picture-only question has no words to encode"


def test_an_unreadable_query_image_is_the_caller_s_problem(tmp_path: Path) -> None:
    index, settings, database, encoder = _index(tmp_path)
    _image_atom(tmp_path, settings, database, "pic1", 1)
    index.build()
    service = _search_service(encoder, settings, database)
    broken = tmp_path / "broken.png"
    broken.write_text("not a picture", encoding="utf-8")

    with pytest.raises(ValueError, match="cannot be read"):
        service.search("", image=broken)


def test_a_search_without_a_snapshot_never_touches_the_encoder(tmp_path: Path) -> None:
    _, settings, database, encoder = _index(tmp_path, with_model=False)
    _image_atom(tmp_path, settings, database, "pic1", 1)
    service = _search_service(encoder, settings, database)

    result = service.search("pic1", top_k=2)

    assert encoder.text_calls == 0
    assert all(hit.visual_score == 0.0 for hit in result.hits)
