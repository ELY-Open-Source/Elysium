"""The LEGS page: one markdown table per question the harness was built to answer."""

from pathlib import Path
from typing import Any


def write_markdown(report: dict[str, Any], path: Path) -> None:
    machine = report["machine"]
    header = [
        "| leg configuration | atoms asked | recall@10 | MRR | hit@10 | 95% lower | newest first | p50 ms | p95 ms | distinct sources |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    rows = []
    for arm in report["arms"]:
        newest = arm["newest_gold_first"]
        rows.append(
            f"| {arm['label']} | {arm['top_k']} | {arm['recall_at_10']:.3f} | {arm['mrr']:.3f} | "
            f"{arm['hit_at_10']:.3f} | {arm['wilson_lower']:.3f} | "
            f"{'—' if newest is None else f'{newest:.2f}'} | {arm['p50_seconds'] * 1000:.1f} | "
            f"{arm['p95_seconds'] * 1000:.1f} | {arm['median_distinct_sources']} |"
        )
    modalities = sorted({modality for arm in report["arms"] for modality in arm["by_modality"]})
    modality_rows = [
        "| leg configuration | " + " | ".join(modalities) + " |",
        "| --- |" + " --- |" * len(modalities),
    ]
    for arm in report["arms"]:
        modality_rows.append(
            f"| {arm['label']} | "
            + " | ".join(f"{arm['by_modality'].get(modality, float('nan')):.3f}" for modality in modalities)
            + " |"
        )
    counts = report["arms"][0]["modality_counts"]

    def memory_table(title: str, field: str, sizes_field: str) -> list[str]:
        """A table over the question types the memory set labels; unlabelled sets stay out of it."""
        rows = [arm["memory"] for arm in report["arms"]]
        names = sorted({name for row in rows for name in row[field] if name != "unlabelled"})
        if not names:
            return []
        lines = [
            f"## {title}",
            "",
            "| leg configuration | " + " | ".join(names) + " |",
            "| --- |" + " --- |" * len(names),
        ]
        for arm, row in zip(report["arms"], rows, strict=True):
            values, sizes = row[field], row[sizes_field]
            cells = []
            for name in names:
                if name not in values:
                    cells.append("—")
                elif field == "by_category":
                    cells.append(f"{values[name]:.3f}")
                else:
                    cells.append(f"{values[name]:.2f} ({sizes[name]})")
            lines.append(f"| {arm['label']} | " + " | ".join(cells) + " |")
        sizes = rows[0][sizes_field]
        lines += [
            "",
            "_Queries per type: "
            + ", ".join(f"{name} {size}" for name, size in sizes.items() if name != "unlabelled")
            + "._",
        ]
        return lines
    path.write_text(
        "\n".join(
            [
                "# LEGS: what each retrieval leg is worth",
                "",
                f"- commit: `{report['commit']}`, schema v{report['schema_version']}",
                (
                    f"- store: {report['store']} — a copy of {report['source_store']}, which carries "
                    f"{report['dense_vectors']:,} dense vectors built by bench/dense_scale. The build "
                    "sits outside the measured latency, and the frozen baseline itself holds no "
                    "vectors, so a dense arm there would rank an empty index."
                ),
                f"- {report['probes']} answerable queries, each asked as the holder the frozen set assigns it",
                (
                    f"- memory subset: every answerable {report['memory_modality']} query "
                    f"({report['memory_queries']}) measured whole, because a 15-probe sample cannot "
                    "separate six question types; the two tables further down use that subset, not the sample"
                ),
                *(
                    []
                    if report.get("picture_index") is None
                    else [
                        (
                            f"- picture index: {report['picture_index']['atoms']:,} atoms at "
                            f"{report['picture_index']['dim']} dimensions, "
                            f"{report['picture_index']['bytes']:,} bytes, read from "
                            f"{report['picture_index']['path']}"
                        ),
                        (
                            f"- encoder speed: {report['encode_rate']['per_second']:.1f} pictures/s "
                            f"measured on {report['encode_rate']['pictures']} pictures, so the "
                            f"{report['picture_index']['atoms']:,} pictures in that index cost about "
                            f"{report['picture_index']['atoms'] / report['encode_rate']['per_second'] / 60:.1f} "
                            "minutes to encode"
                        ),
                    ]
                ),
                (
                    f"- machine: {machine['system']} {machine['release']}, {machine['cpus']} cores, "
                    f"{machine['threads_per_query']} threads per query, load {machine['load_average_1_5_15']}"
                ),
                "",
                "Recall is scored on the first ten **sources** after atoms are collapsed to their source",
                "by first hit, which is how every other arm in this repo is scored.",
                "",
                *header,
                *rows,
                "",
                "## recall@10 by modality",
                "",
                *modality_rows,
                "",
                f"_Query counts per modality: {', '.join(f'{name} {count}' for name, count in counts.items())}._",
                "",
                *memory_table("recall@10 by question type, every memory query measured", "by_category", "category_counts"),
                "",
                *memory_table(
                    "the newest of the gold memories came back first",
                    "newest_gold_first_by_category",
                    "newest_gold_first_counts",
                ),
                "",
                (
                    "recall@10 counts any gold memory, so a knowledge-update question can score 1.000 "
                    "while the ranking still leads with the value the speaker has since replaced. The "
                    "table above asks the sharper question: when the answer lives in several dated "
                    "memories, is the newest one the first one returned? Only questions with at least two "
                    "dated gold memories and at least one returned are counted."
                ),
                "",
                (
                    "The picture leg is not a switch this harness flips per row: the product runs it only "
                    "when the sparse page comes back thin, so these rows measure the product with the leg "
                    "available, not a forced always-on fusion."
                ),
                "",
                (
                    "_Latency is wall time per search on the machine named above with the thread budget "
                    "the benchmark pins; a run on a loaded machine is not comparable._"
                ),
                "",
            ]
        ),
        encoding="utf-8",
    )
