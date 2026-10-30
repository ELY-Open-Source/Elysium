"""Can a library of wordless pictures be searched?

ScreenSpot-v2 is the only corpus in this suite whose gold answer is a *region of a screen*, and
its icon targets carry almost no text. That makes it the honest test of the picture index: a
sentence about an icon has to reach the icon itself, not a transcription of it.

Six arms, three questions:

  words        BM25 over whatever OCR found — what the product did before any picture vector
  picture      a sentence, or a whole screenshot, asked of the CLIP space
  pool         the same question at three granularities: among all icon crops, among whole
               screenshots, and among the icons of one screen (the shape ScreenSpot itself poses)
"""

from __future__ import annotations

import hashlib
import json
import re
import statistics
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from elysian.config import Settings
from elysian.db import Database
from elysian.ocr import read_text_from_image
from elysian.retrieval import RetrievalService
from elysian.schemas import (
    EvidenceAtom,
    Modality,
    SourceRecord,
    TrustScores,
)
from elysian.storage import (
    ObjectStore,
    token_equivalent,
    visual_token_equivalent,
)
from elysian.visual_index import VisualIndex

from bench.metrics import aggregate, chance_recall_at_k, score_query
from bench.systems import machine_facts

ROOT = Path(__file__).resolve().parent
CORPUS = ROOT / "corpus" / "OS-Copilot" / "ScreenSpot-v2"
IMAGES = CORPUS / "images"
IMAGE_ZIP = CORPUS / "screenspotv2_image.zip"
CROPS = ROOT / "runs" / "visual" / "crops"
HOME = ROOT / "runs" / "visual"
MODEL_DIR = ROOT / "models" / "chinese-clip-vit-base-patch16"
REPORTS = ROOT / "reports"
TOP_K = 10


@dataclass(frozen=True)
class Arm:
    """One way to ask, one pool to answer from, one kind of gold."""

    label: str
    signal: str  # words | picture_words | picture
    pool: str  # crops | shots | own_screen
    gold: str  # crop | screen

    @property
    def key(self) -> str:
        return f"{self.signal}->{self.pool}"


ARMS = (
    Arm("words → icon crops", "words", "crops", "crop"),
    Arm("a sentence → icon crops (picture space)", "picture_words", "crops", "crop"),
    Arm("the whole screenshot → icon crops", "picture", "crops", "crop"),
    Arm("words → whole screenshots", "words", "shots", "screen"),
    Arm("a sentence → whole screenshots (picture space)", "picture_words", "shots", "screen"),
    Arm("a sentence → the icons of that one screen", "picture_words", "own_screen", "crop"),
)


def git_commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT.parent, check=True, capture_output=True, text=True
    ).stdout.strip()


def model_sha256() -> str:
    graph = MODEL_DIR / "onnx" / "model_fp16.onnx"
    if not graph.exists():
        raise SystemExit(f"{graph} is missing; fetch the Chinese-CLIP fp16 export first")
    digest = hashlib.sha256()
    with graph.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def ensure_images() -> None:
    """The dataset ships its screenshots inside one zip; unpack them once, flat."""
    if IMAGES.exists() and any(IMAGES.iterdir()):
        return
    if not IMAGE_ZIP.exists():
        raise SystemExit(f"{IMAGE_ZIP} is missing; download the ScreenSpot-v2 corpus first")
    import zipfile

    started = time.monotonic()
    with zipfile.ZipFile(IMAGE_ZIP) as archive:
        names = [name for name in archive.namelist() if name.lower().endswith((".png", ".jpg", ".jpeg"))]
        IMAGES.mkdir(parents=True, exist_ok=True)
        for name in names:
            target = IMAGES / Path(name).name
            if not target.exists():
                target.write_bytes(archive.read(name))
    print(f"unpacked {len(names)} screenshots into {IMAGES} in {time.monotonic() - started:.1f}s", flush=True)


def icon_targets() -> list[dict[str, Any]]:
    """Every icon instruction, with its crop and the screenshot it came from."""
    ensure_images()
    targets: list[dict[str, Any]] = []
    for name in ("mobile", "desktop", "web"):
        rows = _read_rows(CORPUS / f"screenspot_{name}_v2.json")
        for row in rows:
            if row.get("data_type") != "icon":
                continue
            picture = CORPUS / "images" / row["img_filename"]
            if not picture.exists():
                raise SystemExit(f"{picture}: ScreenSpot names a screenshot that is not on disk")
            stem = Path(row["img_filename"]).stem
            crop_path = CROPS / f"{stem}-{len(targets)}.png"
            screenshot_path = CROPS / f"{stem}-full.png"
            CROPS.mkdir(parents=True, exist_ok=True)
            from PIL import Image

            with Image.open(picture) as screen:
                left, top, width, height = [int(value) for value in row["bbox"]]
                if not crop_path.exists():
                    screen.crop((left, top, left + width, top + height)).convert("RGB").save(crop_path)
                if not screenshot_path.exists():
                    screen.convert("RGB").save(screenshot_path)
            targets.append(
                {
                    "instruction": row["instruction"],
                    "source_id": f"{stem}-icon-{len(targets)}",
                    "screen_id": f"screen-{stem}",
                    "crop": crop_path,
                    "screenshot": screenshot_path,
                    "size": (width, height),
                    "holder": row.get("data_source"),
                }
            )
    if not targets:
        raise SystemExit(f"{CORPUS}: no icon targets found; is the ScreenSpot-v2 corpus downloaded?")
    return targets


def screenshot_targets(targets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One memory per distinct screenshot: the granularity the product actually stores."""
    screens: dict[str, dict[str, Any]] = {}
    for target in targets:
        screen = screens.setdefault(
            target["screen_id"],
            {"source_id": target["screen_id"], "screenshot": target["screenshot"], "crops": []},
        )
        screen["crops"].append(target["source_id"])
    return list(screens.values())


def _read_rows(path: Path) -> list[dict[str, Any]]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"{path}: the ScreenSpot instruction file is unreadable ({error})") from error


def _atom(settings: Settings, store: ObjectStore, path: Path, source_id: str, modality: Modality) -> EvidenceAtom:
    ocr = read_text_from_image(path)
    width, height = _size(path)
    return EvidenceAtom(
        atom_id=f"{source_id}:image",
        modality=modality,
        source_id=source_id,
        source=str(path),
        text=ocr.text,
        image_ref=store.put_file(path, "images"),
        trust=TrustScores(parser=1.0, ocr=ocr.confidence, model=0.0),
        token_equivalent=token_equivalent(ocr.text) + visual_token_equivalent(width, height),
        scenario="ui-referencing",
    )


def ingest(settings: Settings, targets: list[dict[str, Any]], screens: list[dict[str, Any]]) -> None:
    """Store each crop and each screenshot as one memory, the way ingestion would."""
    database = Database(settings)
    store = ObjectStore(settings)
    atoms: list[EvidenceAtom] = []
    sources: list[SourceRecord] = []
    for position, target in enumerate(targets):
        path = Path(target["crop"])
        atoms.append(_atom(settings, store, path, str(target["source_id"]), Modality.image))
        sources.append(_source(str(target["source_id"]), path))
        if (position + 1) % 100 == 0:
            print(f"ingested {position + 1}/{len(targets)} crops", flush=True)
    for position, screen in enumerate(screens):
        path = Path(screen["screenshot"])
        atoms.append(_atom(settings, store, path, str(screen["source_id"]), Modality.ui_screenshot))
        sources.append(_source(str(screen["source_id"]), path))
        if (position + 1) % 100 == 0:
            print(f"ingested {position + 1}/{len(screens)} screenshots", flush=True)
    database.upsert_sources(sources)
    database.upsert_atoms(atoms)


def _source(source_id: str, path: Path) -> SourceRecord:
    return SourceRecord(
        source_id=source_id,
        path=str(path),
        kind="image",
        mime="image/png",
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        size_bytes=path.stat().st_size,
    )


def _size(path: Path) -> tuple[int, int]:
    from PIL import Image

    with Image.open(path) as picture:
        return picture.size


def run_arm(
    arm: Arm,
    targets: list[dict[str, Any]],
    pools: dict[str, Any],
    index: VisualIndex,
    retrieval: RetrievalService,
    source_of_atom: dict[str, str],
) -> tuple[list[list[str]], list[float]]:
    """Ask every instruction one way, and keep the answers in corpus ids."""
    ranked: list[list[str]] = []
    seconds: list[float] = []
    for position, target in enumerate(targets):
        pool = _pool(arm, target, pools)
        started = time.monotonic()
        if arm.signal == "words":
            hits = [hit.atom.atom_id for hit in retrieval.search(target["instruction"], TOP_K * 4).hits]
            answer = [hit for hit in hits if pool is None or hit in pool][:TOP_K]
        elif arm.signal == "picture_words":
            answer = [atom_id for atom_id, _ in index.search_text(target["instruction"], TOP_K, pool)]
        else:
            answer = [atom_id for atom_id, _ in index.search_image(target["screenshot"], TOP_K, pool)]
        seconds.append(time.monotonic() - started)
        ranked.append([source_of_atom[atom_id] for atom_id in answer if atom_id in source_of_atom])
        if (position + 1) % 100 == 0:
            print(f"{arm.label}: {position + 1}/{len(targets)}", flush=True)
    return ranked, seconds


def _pool(arm: Arm, target: dict[str, Any], pools: dict[str, Any]) -> set[str] | None:
    if arm.pool == "own_screen":
        return {
            atom_id
            for atom_id, source_id in pools["atom_of_target"].items()
            if source_id in set(pools["screen_crops"][target["screen_id"]])
        }
    return pools.get(arm.pool)


def score(arm: Arm, targets: list[dict[str, Any]], ranked: list[list[str]], seconds: list[float]) -> dict[str, Any]:
    scores = [
        score_query(
            f"{target['source_id']}, {target['instruction'][:40]}",
            hits,
            {target["source_id"] if arm.gold == "crop" else target["screen_id"]},
        )
        for target, hits in zip(targets, ranked, strict=True)
    ]
    ordered = sorted(seconds)
    return {
        "label": arm.label,
        "key": arm.key,
        **aggregate(scores),
        "latency": {
            "queries": len(scores),
            "p50": round(statistics.median(ordered), 4),
            "p95": round(ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))], 4),
        },
    }


def main() -> None:
    settings = Settings(home=HOME, clip_model_dir=MODEL_DIR)
    targets = icon_targets()
    screens = screenshot_targets(targets)
    database = Database(settings)
    if database.atom_count() != len(targets) + len(screens):
        started = time.monotonic()
        ingest(settings, targets, screens)
        print(f"ingested {len(targets)} crops + {len(screens)} screenshots in {time.monotonic() - started:.1f}s", flush=True)
    source_of_atom = {atom.atom_id: atom.source_id for atom in database.list_atoms()}
    crops = {atom.atom_id for atom in database.list_atoms() if atom.modality is Modality.image}
    shots = {atom.atom_id for atom in database.list_atoms() if atom.modality is Modality.ui_screenshot}
    wordless = sum(
        1 for atom in database.list_atoms() if atom.atom_id in crops and not atom.text.strip()
    )

    index = VisualIndex(settings, database)
    if not index.is_current():
        started = time.monotonic()
        built = index.build()
        print(f"encoded {built} in {time.monotonic() - started:.1f}s", flush=True)
    retrieval = RetrievalService(settings, database)

    pools = {
        "crops": crops,
        "shots": shots,
        "atom_of_target": source_of_atom,
        "screen_crops": {screen["source_id"]: screen["crops"] for screen in screens},
    }
    per_screen = [len(screen["crops"]) for screen in screens]
    rows = []
    for arm in ARMS:
        ranked, seconds = run_arm(arm, targets, pools, index, retrieval, source_of_atom)
        row = score(arm, targets, ranked, seconds)
        row["chance_recall_at_10"] = round(
            chance_recall_at_k(
                1,
                len(crops) if arm.pool == "crops" else len(shots) if arm.pool == "shots" else int(statistics.median(per_screen)),
                TOP_K,
            ),
            4,
        )
        row["pool"] = arm.pool
        rows.append(row)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "commit": git_commit(),
        "dataset": "OS-Copilot/ScreenSpot-v2 (icon instructions)",
        "model": {"repo": "Xenova/chinese-clip-vit-base-patch16", "sha256": model_sha256()},
        "targets": len(targets),
        "screenshots": len(screens),
        "crops_without_ocr_text": wordless,
        "instruction_languages": {
            "cjk_instructions": sum(1 for t in targets if re.search(r"[一-鿿]", t["instruction"]))
        },
        "machine": machine_facts(),
        "arms": rows,
    }
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "visual.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (REPORTS / "VISUAL.md").write_text(markdown(report), encoding="utf-8")
    for row in rows:
        print(
            f"{row['label']}: recall@10 {row['recall_at_10']:.3f} (chance {row['chance_recall_at_10']:.3f}) "
            f"mrr {row['mrr']:.3f} p50 {row['latency']['p50']}s"
        )
    print(f"wrote {REPORTS / 'VISUAL.md'}")


def markdown(report: dict[str, Any]) -> str:
    lines = [
        f"# VISUAL: can a library of wordless pictures be searched? (commit {report['commit'][:9]})",
        "",
        f"- generated {report['generated_at']}",
        (
            f"- corpus: {report['dataset']}, {report['targets']} icon crops and {report['screenshots']} whole "
            f"screenshots stored as separate memories, {report['crops_without_ocr_text']} crops with no OCR text"
        ),
        f"- encoder: {report['model']['repo']} sha256 {report['model']['sha256'][:16]}",
        f"- machine: {report['machine']['cpus']} cpus, load {report['machine']['load_average_1_5_15']}",
        (
            f"- instructions containing Chinese: {report['instruction_languages']['cjk_instructions']} "
            "(ScreenSpot-v2 is English, so this run does not test the bilingual claim)"
        ),
        "",
        "| ask | pool | recall@1 | recall@5 | recall@10 | chance@10 | MRR | hit@10 lower 95% | p50 s | p95 s |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in report["arms"]:
        lines.append(
            f"| {row['label']} | {row['pool']} | {row['recall_at_1']:.3f} | {row['recall_at_5']:.3f} "
            f"| {row['recall_at_10']:.3f} | {row['chance_recall_at_10']:.4f} | {row['mrr']:.3f} "
            f"| {row['hit_at_10_wilson_lower']:.3f} | {row['latency']['p50']} | {row['latency']['p95']} |"
        )
    lines += [
        "",
        (
            "The words rows are what the product could do before any picture vector: if OCR found no words, "
            "there is nothing to match. The picture rows ask the same sentence, or the whole screenshot, of the "
            "CLIP space. The pools change the question: among every icon in the library, among whole screenshots "
            "(the granularity the store keeps), and among one screen's icons, which is the shape ScreenSpot "
            "itself poses. A number is only comparable inside its own pool, so chance is printed per row."
        ),
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    main()
