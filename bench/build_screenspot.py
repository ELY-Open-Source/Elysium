"""Build UI-screenshot referring sets from ScreenSpot-v2.

Gold regions are human-drawn element boxes in [x, y, w, h] pixels; the box
convention was verified against image dimensions (1271/1272 boxes in bounds as
xywh, 61 as xyxy). Each data_source domain is one memory holder, so an
instruction can also be asked of a holder that never saw that screen.
"""

from __future__ import annotations

import json
import zipfile
from typing import Any

from bench.corpus_sources import source_for
from bench.sets_common import (
    DATA_ROOT,
    SETS,
    corpus_path,
    corpus_record,
    parse_json_array,
    query_record,
    safe_segment,
    sample_by_holder,
    write_jsonl,
)

DATASET = "OS-Copilot/ScreenSpot-v2"
IMAGES = DATA_ROOT / "screenspot"
ANNOTATIONS = (
    "screenspot_mobile_v2.json",
    "screenspot_desktop_v2.json",
    "screenspot_web_v2.json",
)
SCENARIO = "ui-referencing"


def extract_images() -> dict[str, str]:
    """Unpack the screenshot zip flat under DATA_ROOT/screenspot; name -> relative path."""
    archive = corpus_path(DATASET, "screenspotv2_image.zip")
    IMAGES.mkdir(parents=True, exist_ok=True)
    mapping: dict[str, str] = {}
    with zipfile.ZipFile(archive) as bundle:
        for info in bundle.infolist():
            if info.is_dir():
                continue
            name = info.filename.rsplit("/", 1)[-1]
            if not name.lower().endswith((".png", ".jpg", ".jpeg")):
                continue
            name = safe_segment(name, f"archive entry {info.filename!r}")
            if name in mapping:
                raise SystemExit(f"{archive}: {info.filename} collides with an earlier entry named {name}")
            target = IMAGES / name
            if not target.is_file() or target.stat().st_size == 0:
                target.write_bytes(bundle.read(info))
            mapping[name] = target.relative_to(IMAGES.parent).as_posix()
    if not mapping:
        raise SystemExit(f"{archive}: no images found in the screenshot archive")
    return mapping


def box_of(row: dict[str, Any], where: str) -> list[int]:
    raw = row["bbox"]
    box = raw if isinstance(raw, list) else parse_json_array(str(raw), where)
    if len(box) != 4:
        raise SystemExit(f"{where}: expected a 4-number bbox, got {raw!r}")
    return [_as_int(value, where) for value in box]


def _as_int(value: Any, where: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise SystemExit(f"{where}: expected an integer coordinate, got {value!r}") from exc


def build() -> tuple[list, list, dict]:
    source = source_for(DATASET)
    revision = str(source["revision"])
    observed_at = str(source["snapshot_at"])
    images = extract_images()

    corpus_by_id: dict[str, dict[str, Any]] = {}
    queries: list[dict[str, Any]] = []
    for annotation in ANNOTATIONS:
        path = corpus_path(DATASET, annotation)
        rows = parse_json_array(path.read_text(encoding="utf-8"), str(path))
        for index, row in enumerate(rows):
            where = f"{annotation}:{index}"
            if not isinstance(row, dict):
                raise SystemExit(f"{where}: expected a json object")
            image = str(row["img_filename"])
            instruction = str(row["instruction"]).strip()
            holder = str(row["data_source"])
            if image not in images:
                raise SystemExit(f"{where}: annotation references {image}, absent from the archive")
            if not instruction:
                raise SystemExit(f"{where}: empty instruction")
            source_id = f"screenspot:{image.rsplit('.', 1)[0]}"
            corpus_by_id.setdefault(
                source_id,
                corpus_record(
                    source_id=source_id,
                    modality="ui_screenshot",
                    path=images[image],
                    title=image,
                    observed_at=observed_at,
                    holder=holder,
                    scenario=SCENARIO,
                    root="derived",
                    extra={"data_type": str(row["data_type"])},
                ),
            )
            queries.append(
                query_record(
                    query_id=f"screenspot:{annotation.removeprefix('screenspot_').removesuffix('_v2.json')}:{index}",
                    modality="ui_screenshot",
                    question=instruction,
                    answer=image,
                    answer_format="none",
                    gold=[{"source_id": source_id, "region": {"bbox": box_of(row, where)}}],
                    holder=holder,
                    scenario=SCENARIO,
                    as_of=observed_at,
                    origin={"dataset": DATASET, "revision": revision, "item": f"{annotation}:{index}"},
                )
            )

    holders = sorted({record["holder"] for record in corpus_by_id.values()})
    picked = sample_by_holder(queries)
    unanswerable = cross_holder(picked, holders, revision, observed_at)
    all_queries = picked + unanswerable
    report = {
        "datasets": [DATASET],
        "revision": revision,
        "annotations": len(queries),
        "screenshots": len(corpus_by_id),
        "holders": holders,
        "queries": len(all_queries),
        "queries_answerable": len(picked),
        "queries_cross_holder_unanswerable": len(unanswerable),
    }
    return sorted(corpus_by_id.values(), key=lambda r: r["source_id"]), all_queries, report


def cross_holder(
    queries: list[dict[str, Any]], holders: list[str], revision: str, observed_at: str
) -> list[dict[str, Any]]:
    extras: list[dict[str, Any]] = []
    for query in queries:
        own = query["scope"]["holder"]
        other = holders[(holders.index(own) + 1) % len(holders)]
        extras.append(
            query_record(
                query_id=f"{query['query_id']}@{other}",
                modality="ui_screenshot",
                question=query["question"],
                answer=None,
                answer_format="none",
                gold=[],
                holder=other,
                scenario=SCENARIO,
                as_of=observed_at,
                origin=query["origin"] | {"construction": "cross-holder"},
            )
        )
    return extras


def main() -> None:
    corpus, queries, report = build()
    corpus_count, corpus_sha = write_jsonl(SETS / "corpus" / "ui_screenshot.jsonl", corpus)
    query_count, query_sha = write_jsonl(SETS / "ui_screenshot.jsonl", queries)
    report |= {"corpus_records": corpus_count, "corpus_sha256": corpus_sha, "queries_sha256": query_sha}
    (SETS / "reports").mkdir(parents=True, exist_ok=True)
    (SETS / "reports" / "ui_screenshot.json").write_text(
        json.dumps(report, indent=1, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps(report, indent=1, sort_keys=True))


if __name__ == "__main__":
    main()
