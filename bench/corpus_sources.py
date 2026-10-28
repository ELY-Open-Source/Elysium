"""Pinned corpus sources for the elysium benchmark."""

from typing import Any

SOURCES: list[dict[str, Any]] = [
    {
        "dataset": "yubo2333/MMLongBench-Doc",
        "revision": "2ff6aa9237fc777b6627dc57a486e9225ac5fb86",
        "snapshot_at": "2025-11-06T05:23:19+00:00",
        "modality": "pdf",
        "license": "not-stated-in-card",
        "annotation_source": "MMLongBench-Doc human-written questions with evidence_page_ids, Wang et al. 2024 arXiv:2407.01523",
        "files": "ALL",
    },
    {
        "dataset": "xiaowu0162/longmemeval-cleaned",
        "revision": "98d7416c24c778c2fee6e6f3006e7a073259d48f",
        "snapshot_at": "2025-09-19T23:48:16+00:00",
        "modality": "conversation",
        "license": "mit",
        "annotation_source": "LongMemEval human-authored QA with evidence_session_ids and category labels, Wu et al. 2024 arXiv:2410.10813",
        "files": ["longmemeval_s_cleaned.json"],
    },
    {
        "dataset": "openbmb/VisRAG-Ret-Test-SlideVQA",
        "revision": "6b5f81a3f6953095934c26c5d420dfd039184d69",
        "snapshot_at": "2025-03-15T17:40:55+00:00",
        "modality": "image",
        "license": "not-stated-in-card",
        "annotation_source": "VisRAG-Ret qrels derived from SlideVQA upstream annotations, Yu et al. 2024 arXiv:2410.10594",
        "files": [
            "corpus/train-00000-of-00001.parquet",
            "queries/train-00000-of-00001.parquet",
            "qrels/train-00000-of-00001.parquet",
            "qrels/slidevqa-eval-qrels.tsv",
        ],
    },
    {
        "dataset": "openbmb/VisRAG-Ret-Test-InfoVQA",
        "revision": "04ee2db1d0a05304899453a3b03baef5e18991a3",
        "snapshot_at": "2025-03-15T17:37:21+00:00",
        "modality": "image",
        "license": "not-stated-in-card",
        "annotation_source": "VisRAG-Ret qrels derived from InfoVQA upstream annotations, Mathew et al. 2021",
        "files": [
            "corpus/train-00000-of-00001.parquet",
            "queries/train-00000-of-00001.parquet",
            "qrels/train-00000-of-00001.parquet",
        ],
    },
    {
        "dataset": "openbmb/VisRAG-Ret-Test-ChartQA",
        "revision": "31f5ceb5d60b02e065bff394cb582f5bbb01a9b6",
        "snapshot_at": "2025-03-15T17:58:47+00:00",
        "modality": "image",
        "license": "not-stated-in-card",
        "annotation_source": "VisRAG-Ret qrels derived from ChartQA upstream annotations, Masry et al. 2022",
        "files": [
            "corpus/train-00000-of-00001.parquet",
            "queries/train-00000-of-00001.parquet",
            "qrels/train-00000-of-00001.parquet",
        ],
    },
    {
        "dataset": "openbmb/VisRAG-Ret-Test-MP-DocVQA",
        "revision": "3ebd091c458cf04161f78cd7b12ea101f83e2529",
        "snapshot_at": "2025-03-15T17:36:14+00:00",
        "modality": "image",
        "license": "not-stated-in-card",
        "annotation_source": "VisRAG-Ret qrels derived from DocVQA-MP upstream annotations, Mathew et al. 2021",
        "files": [
            "corpus/train-00000-of-00001.parquet",
            "queries/train-00000-of-00001.parquet",
            "qrels/train-00000-of-00001.parquet",
            "qrels/docvqa_mp-eval-qrels.tsv",
        ],
    },
    {
        "dataset": "openbmb/VisRAG-Ret-Test-PlotQA",
        "revision": "ef953ef8ab6d78ac112dd4cde6acdb2c2692039a",
        "snapshot_at": "2025-03-15T17:38:38+00:00",
        "modality": "image",
        "license": "not-stated-in-card",
        "annotation_source": "VisRAG-Ret qrels derived from PlotQA upstream annotations, Matsuda et al. 2018",
        "files": [
            "corpus/train-00000-of-00001.parquet",
            "queries/train-00000-of-00001.parquet",
            "qrels/train-00000-of-00001.parquet",
            "qrels/plotqa-eval-qrels.tsv",
        ],
    },
    {
        "dataset": "openbmb/VisRAG-Ret-Test-ArxivQA",
        "revision": "00a31fc1e899b5f81d7760eca4907b1a1005865b",
        "snapshot_at": "2025-03-15T17:31:12+00:00",
        "modality": "image",
        "license": "not-stated-in-card",
        "annotation_source": "VisRAG-Ret qrels derived from ArXivQA upstream annotations, Li et al. 2024",
        "files": [
            "corpus/train-00000-of-00003.parquet",
            "corpus/train-00001-of-00003.parquet",
            "corpus/train-00002-of-00003.parquet",
            "queries/train-00000-of-00001.parquet",
            "qrels/train-00000-of-00001.parquet",
            "qrels/arxivqa-eval-qrels.tsv",
        ],
    },
    {
        "dataset": "code-search-net/code_search_net",
        "revision": "bd0cf261e357a3eb5c8fba490d23ec1a1cd59555",
        "snapshot_at": "2026-02-23T14:11:41+00:00",
        "modality": "code",
        "license": "other (per-repository OSS licenses recorded in the dataset's metadata column)",
        "annotation_source": "developer-written docstrings, Husain et al. 2019 (arXiv:1909.09436)",
        "files": [
            "python/test-00000-of-00001.parquet",
            "python/validation-00000-of-00001.parquet",
        ],
    },
    {
        "dataset": "OS-Copilot/ScreenSpot-v2",
        "revision": "5efbb1f1b5463a575f2eb7bc30fe29e49c15f93c",
        "snapshot_at": "2025-02-10T11:15:38+00:00",
        "modality": "ui_screenshot",
        "license": "apache-2.0",
        "annotation_source": "ScreenSpot human-written referring instructions with element bounding boxes, Li et al. 2023 arXiv:2308.08155",
        "files": [
            "screenspotv2_image.zip",
            "screenspot_desktop_v2.json",
            "screenspot_web_v2.json",
            "screenspot_mobile_v2.json",
        ],
    },
    {
        "dataset": "lmms-eval/Video-MME",
        "revision": "ead1408f75b618502df9a1d8e0950166bf0a2a0b",
        "snapshot_at": "2024-07-04T08:14:20+00:00",
        "modality": "video",
        "license": "not-stated-in-card",
        "annotation_source": "Video-MME human-written video QA with duration tiers and subtitle timings, Fu et al. 2024 arXiv:2405.21083",
        "files": [
            "videomme/test-00000-of-00001.parquet",
            "subtitle.zip",
            "videos_chunked_01.zip",
            "videos_chunked_02.zip",
            "videos_chunked_03.zip",
        ],
    },
]

def source_for(dataset: str) -> dict[str, Any]:
    """The pinned entry for a dataset: revision, snapshot date, licence, provenance."""
    for source in SOURCES:
        if source["dataset"] == dataset:
            return source
    raise SystemExit(f"{dataset} is not a pinned corpus source")


GIT_REPOS = [
    {
        "repo": "https://github.com/pyparsing/pyparsing",
        "ref": "master",
        "sha": "f803ae834288032a700331977639fc49c62fcd7f",
        "language": "python",
        "modality": "code",
        "annotation_source": "symbol definitions parsed from upstream source, no model judgement",
    },
    {
        "repo": "https://github.com/rust-lang/regex",
        "ref": "master",
        "sha": "72d650cb0a880a01ab6dc2137c0888e8f89740f7",
        "language": "rust",
        "modality": "code",
        "annotation_source": "symbol definitions parsed from upstream source, no model judgement",
    },
    {
        "repo": "https://github.com/tokio-rs/tokio",
        "ref": "master",
        "sha": "b2636752450484955e7ad334bac678424d51bc4a",
        "language": "rust",
        "modality": "code",
        "annotation_source": "symbol definitions parsed from upstream source, no model judgement",
    },
]
