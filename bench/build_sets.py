"""Run every set builder in one pass and freeze what the whole suite contains.

Each builder writes its own corpus, queries, and report; this orchestrator only
adds the suite-level manifest that pins the corpus snapshot and the digest of
every generated file, so a later run can prove it is measuring the same data.
"""

from __future__ import annotations

import importlib
import json

from bench.sets_common import CORPUS, MODALITIES, SETS, read_jsonl, sha256_file

BUILDERS = {
    "pdf": "bench.build_mmlongbench",
    "image": "bench.build_visrag",
    "ui_screenshot": "bench.build_screenspot",
    "video": "bench.build_videomme",
    "code": "bench.build_code",
    "conversation": "bench.build_longmemeval",
}

if set(BUILDERS) != set(MODALITIES):
    raise SystemExit(
        f"builders cover {sorted(BUILDERS)} but the schema demands {sorted(MODALITIES)}"
    )


def read_report(modality: str) -> dict:
    """A builder that produced no report is a broken build, not a missing optional file."""
    path = SETS / "reports" / f"{modality}.json"
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SystemExit(f"{path}: unreadable builder report: {error}") from error
    if not isinstance(loaded, dict):
        raise SystemExit(f"{path}: expected a json object")
    return loaded


def main() -> None:
    for modality in MODALITIES:
        print(f"== {modality}")
        importlib.import_module(BUILDERS[modality]).main()

    modalities: dict[str, dict] = {}
    for modality in MODALITIES:
        queries = list(read_jsonl(SETS / f"{modality}.jsonl"))
        report = read_report(modality)
        if report.get("queries") != len(queries):
            raise SystemExit(
                f"{modality}: report says {report.get('queries')} queries, "
                f"file holds {len(queries)}"
            )
        datasets = report.get("datasets")
        holders = report.get("holders")
        if not isinstance(datasets, list) or not all(isinstance(d, str) for d in datasets):
            raise SystemExit(f"{modality}: report must name its upstream datasets, got {datasets!r}")
        if not isinstance(holders, list) or not all(isinstance(h, str) for h in holders):
            raise SystemExit(f"{modality}: report must name its holders, got {holders!r}")
        modalities[modality] = {
            "corpus_file": f"corpus/{modality}.jsonl",
            "corpus_records": sum(1 for _ in read_jsonl(SETS / "corpus" / f"{modality}.jsonl")),
            "corpus_sha256": sha256_file(SETS / "corpus" / f"{modality}.jsonl"),
            "queries_file": f"{modality}.jsonl",
            "queries": len(queries),
            "queries_answerable": sum(1 for query in queries if not query["unanswerable"]),
            "queries_unanswerable": sum(1 for query in queries if query["unanswerable"]),
            "queries_sha256": sha256_file(SETS / f"{modality}.jsonl"),
            "holders": holders,
            "sources": datasets,
        }

    manifest = {
        "corpus_manifest": "corpus/manifest.jsonl",
        "corpus_manifest_sha256": sha256_file(CORPUS / "manifest.jsonl"),
        "modalities": modalities,
        "corpus_records": sum(item["corpus_records"] for item in modalities.values()),
        "queries": sum(item["queries"] for item in modalities.values()),
        "queries_answerable": sum(item["queries_answerable"] for item in modalities.values()),
        "queries_unanswerable": sum(item["queries_unanswerable"] for item in modalities.values()),
        "holders": sum(len(item["holders"]) for item in modalities.values()),
    }
    path = SETS / "manifest.json"
    path.write_text(json.dumps(manifest, indent=1, sort_keys=True), encoding="utf-8")
    print(
        json.dumps(
            {
                "corpus_records": manifest["corpus_records"],
                "queries": manifest["queries"],
                "queries_answerable": manifest["queries_answerable"],
                "queries_unanswerable": manifest["queries_unanswerable"],
                "holders": manifest["holders"],
                "corpus_manifest_sha256": manifest["corpus_manifest_sha256"][:16],
                "manifest": str(path),
            },
            indent=1,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
