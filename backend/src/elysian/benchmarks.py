from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from .benchmark_scoring import (
    benchmark_prompt,
    benchmark_score,
    canonical_answer,
    exact_or_contains_score,
    extract_answer,
    first_present,
    first_present_raw,
    get_nested,
    normalize_sample,
    prepare_prediction_media,
    sample_identifier,
    sha256_bytes,
    sha256_json,
    slugify,
)
from .evaluation_schemas import (
    BenchmarkPredictionReport,
    BenchmarkPredictionStatus,
    BenchmarkRegistryReport,
    BenchmarkSampleReport,
    BenchmarkSampleStatus,
    BenchmarkSourceReport,
    BenchmarkSourceStatus,
    BenchmarkSpec,
)

STANDARD_BENCHMARKS = (
    BenchmarkSpec(
        name="MMMU-Pro",
        target="Multimodal reasoning within Qwen3.5-9B baseline +/-2%.",
        dataset="MMMU/MMMU_Pro",
        task_type="image_text_multiple_choice",
        runner="elysian run-benchmark --benchmark mmmu-pro --dataset-path <local-jsonl-or-parquet>",
        metric="accuracy",
    ),
    BenchmarkSpec(
        name="OCRBench",
        target="OCR and document understanding at or above base model behavior.",
        dataset="echo840/OCRBench",
        task_type="image_text_qa",
        runner="elysian run-benchmark --benchmark ocrbench --dataset-path <local-jsonl-or-parquet>",
        metric="exact_or_contains_accuracy",
    ),
    BenchmarkSpec(
        name="MMLongBench-Doc",
        target="Long document QA above a RAG-only baseline.",
        dataset="VLM2Vec/MMLongBench-doc",
        task_type="long_document_qa",
        runner="elysian run-benchmark --benchmark mmlongbench-doc --dataset-path <local-jsonl-or-parquet>",
        metric="answer_f1_with_evidence",
    ),
    BenchmarkSpec(
        name="VideoMME",
        target="Long video understanding with sampled visual timeline evidence.",
        dataset="lmms-lab/Video-MME",
        task_type="video_multiple_choice",
        runner="elysian run-benchmark --benchmark videomme --dataset-path <local-jsonl-or-parquet>",
        metric="accuracy",
    ),
    BenchmarkSpec(
        name="LongVideoBench",
        target="Long-context interleaved video-language understanding.",
        dataset="longvideobench/LongVideoBench",
        task_type="video_qa",
        runner="elysian run-benchmark --benchmark longvideobench --dataset-path <local-jsonl-or-parquet>",
        metric="accuracy",
    ),
    BenchmarkSpec(
        name="RULER",
        target="Long-context retrieval, aggregation, and multi-hop reasoning.",
        dataset="RULER-dataset/RULER",
        task_type="long_context_text",
        runner="elysian run-benchmark --benchmark ruler --dataset-path <local-jsonl-or-parquet>",
        metric="task_accuracy",
    ),
    BenchmarkSpec(
        name="LongBench v2",
        target="Long text, multi-document, code, and structured-data reasoning.",
        dataset="THUDM/LongBench-v2",
        task_type="long_context_multiple_choice",
        runner="elysian run-benchmark --benchmark longbench-v2 --dataset-path <local-jsonl-or-parquet>",
        metric="accuracy",
    ),
)

BENCHMARK_PREDICTION_NAMES = ("MMMU-Pro", "OCRBench")

BENCHMARK_SAMPLE_LOADS: dict[str, tuple[str | None, str]] = {
    "MMMU-Pro": ("standard (10 options)", "test"),
    "OCRBench": ("default", "test"),
    "MMLongBench-Doc": ("queries", "test"),
    "VideoMME": ("videomme", "test"),
    "LongVideoBench": (None, "test"),
    "RULER": ("default", "test"),
    "LongBench v2": ("default", "train"),
}

BENCHMARK_SAMPLE_SOURCES: dict[str, tuple[str, str | None, str, str | None]] = {
    "LongVideoBench": (
        "longvideobench/LongVideoBench-Meta",
        "default",
        "validation",
        "Official public metadata release for the gated LongVideoBench media dataset.",
    ),
}


def benchmark_registry_report() -> BenchmarkRegistryReport:
    return BenchmarkRegistryReport(status="ready", benchmarks=list(STANDARD_BENCHMARKS))


def benchmark_source_report(timeout: int = 20) -> BenchmarkSourceReport:
    from huggingface_hub import HfApi

    api = HfApi()
    sources: list[BenchmarkSourceStatus] = []
    for benchmark in STANDARD_BENCHMARKS:
        try:
            info = api.dataset_info(benchmark.dataset, timeout=timeout)
            siblings = getattr(info, "siblings", None) or []
            sources.append(
                BenchmarkSourceStatus(
                    name=benchmark.name,
                    dataset=benchmark.dataset,
                    status="ready" if info.sha else "unavailable",
                    sha=info.sha,
                    gated=getattr(info, "gated", None),
                    private=getattr(info, "private", None),
                    sibling_count=len(siblings),
                )
            )
        except Exception as exc:  # noqa: BLE001  # a probe records its failure instead of crashing the proof run
            sources.append(
                BenchmarkSourceStatus(
                    name=benchmark.name,
                    dataset=benchmark.dataset,
                    status="unavailable",
                    error=str(exc).splitlines()[0],
                )
            )
    status = "ready" if all(source.status == "ready" and source.sha for source in sources) else "incomplete"
    return BenchmarkSourceReport(status=status, sources=sources)


def benchmark_sample_report(output_dir: Path | None = None) -> BenchmarkSampleReport:
    output_root = output_dir or Path(tempfile.mkdtemp(prefix="elysian_benchmark_samples_"))
    output_root.mkdir(parents=True, exist_ok=True)
    samples = [load_benchmark_sample(benchmark, output_root) for benchmark in STANDARD_BENCHMARKS]
    loaded = [sample for sample in samples if sample.status == "loaded"]
    gated = [sample for sample in samples if sample.status == "gated"]
    failed = [sample for sample in samples if sample.status == "failed"]
    if len(loaded) == len(samples):
        status = "ready"
    elif loaded and gated and not failed:
        status = "partial"
    else:
        status = "failed"
    return BenchmarkSampleReport(status=status, samples=samples)


def benchmark_prediction_report(
    settings: Any,
    output_dir: Path | None = None,
    names: tuple[str, ...] = BENCHMARK_PREDICTION_NAMES,
) -> BenchmarkPredictionReport:
    from .runtime import QwenRuntime

    output_root = output_dir or Path(tempfile.mkdtemp(prefix="elysian_benchmark_predictions_"))
    output_root.mkdir(parents=True, exist_ok=True)
    selected = {name.lower() for name in names}
    benchmarks = [benchmark for benchmark in STANDARD_BENCHMARKS if benchmark.name.lower() in selected]
    prediction_settings = settings.model_copy(update={"max_new_tokens": 96, "temperature": 0.0})
    runtime = QwenRuntime(prediction_settings)
    try:
        predictions = [
            predict_benchmark_sample(benchmark, output_root, runtime)
            for benchmark in benchmarks
        ]
    finally:
        runtime.unload()
    predicted = [prediction for prediction in predictions if prediction.status == "predicted"]
    gated = [prediction for prediction in predictions if prediction.status == "gated"]
    failed = [prediction for prediction in predictions if prediction.status == "failed"]
    if len(predicted) == len(predictions) and predictions:
        status = "ready"
    elif predicted and gated and not failed:
        status = "partial"
    else:
        status = "failed"
    return BenchmarkPredictionReport(status=status, predictions=predictions)


def load_benchmark_sample(benchmark: BenchmarkSpec, output_root: Path) -> BenchmarkSampleStatus:
    source_dataset, config, split, source_note = benchmark_sample_source(benchmark)
    try:
        from datasets import load_dataset

        dataset_kwargs: dict[str, Any] = {"split": split, "streaming": True}
        stream = (
            load_dataset(source_dataset, config, **dataset_kwargs)
            if config
            else load_dataset(source_dataset, **dataset_kwargs)
        )
        row = next(iter(stream))
        sample_root = output_root / slugify(benchmark.name)
        sample_root.mkdir(parents=True, exist_ok=True)
        normalized, media_artifacts = normalize_sample(row, sample_root)
        return BenchmarkSampleStatus(
            name=benchmark.name,
            dataset=benchmark.dataset,
            source_dataset=source_dataset,
            source_sha=dataset_sha(source_dataset),
            source_note=source_note,
            status="loaded",
            config=config,
            split=split,
            sample_id=sample_identifier(row),
            fields=list(row.keys()),
            question_preview=first_present(row, ("question", "query", "text")),
            answer_preview=first_present(row, ("answer", "answers", "la", "label", "correct_choice")),
            sample_sha256=sha256_json(normalized),
            media_artifacts=media_artifacts,
        )
    except Exception as exc:  # noqa: BLE001  # a probe records its failure instead of crashing the proof run
        message = str(exc).splitlines()[0]
        status = "gated" if "gated dataset" in message.lower() or "authenticated" in message.lower() else "failed"
        return BenchmarkSampleStatus(
            name=benchmark.name,
            dataset=benchmark.dataset,
            source_dataset=source_dataset,
            source_note=source_note,
            status=status,
            config=config,
            split=split,
            error=message,
        )


def predict_benchmark_sample(benchmark: BenchmarkSpec, output_root: Path, runtime: Any) -> BenchmarkPredictionStatus:
    try:
        from datasets import load_dataset

        config, split = BENCHMARK_SAMPLE_LOADS.get(benchmark.name, (None, "test"))
        dataset_kwargs: dict[str, Any] = {"split": split, "streaming": True}
        stream = (
            load_dataset(benchmark.dataset, config, **dataset_kwargs)
            if config
            else load_dataset(benchmark.dataset, **dataset_kwargs)
        )
        row = next(iter(stream))
        sample_root = output_root / slugify(benchmark.name)
        sample_root.mkdir(parents=True, exist_ok=True)
        normalized, media_artifacts = normalize_sample(row, sample_root)
        prediction_media = prepare_prediction_media(benchmark, media_artifacts)
        prompt = benchmark_prompt(benchmark, row)
        generation = runtime.generate_prompt(prompt, [Path(path) for path in prediction_media])
        prediction = extract_answer(generation.text)
        answer = canonical_answer(first_present_raw(row, ("answer", "answers", "la", "label")))
        score = benchmark_score(benchmark, row, prediction, answer) if answer else None
        return BenchmarkPredictionStatus(
            name=benchmark.name,
            dataset=benchmark.dataset,
            status="predicted",
            config=config,
            split=split,
            sample_id=sample_identifier(row),
            task_type=benchmark.task_type,
            metric=benchmark.metric,
            prompt_sha256=sha256_bytes(prompt.encode("utf-8")),
            sample_sha256=sha256_json(normalized),
            prediction=prediction,
            answer=answer,
            score=score,
            runtime_backend=generation.backend,
            adapter_id=generation.adapter_id,
            adapter_sha256=generation.adapter_sha256,
            input_tokens=generation.input_tokens,
            output_tokens=generation.output_tokens,
            media_artifacts=prediction_media,
        )
    except Exception as exc:  # noqa: BLE001  # a probe records its failure instead of crashing the proof run
        message = str(exc).splitlines()[0]
        status = "gated" if "gated dataset" in message.lower() or "authenticated" in message.lower() else "failed"
        config, split = BENCHMARK_SAMPLE_LOADS.get(benchmark.name, (None, None))
        return BenchmarkPredictionStatus(
            name=benchmark.name,
            dataset=benchmark.dataset,
            status=status,
            config=config,
            split=split,
            task_type=benchmark.task_type,
            metric=benchmark.metric,
            error=message,
        )


def normalize_benchmark_name(name: str) -> str:
    return name.lower().replace("_", "-")


def benchmark_sample_source(benchmark: BenchmarkSpec) -> tuple[str, str | None, str, str | None]:
    override = BENCHMARK_SAMPLE_SOURCES.get(benchmark.name)
    if override is not None:
        return override
    config, split = BENCHMARK_SAMPLE_LOADS.get(benchmark.name, (None, "test"))
    return benchmark.dataset, config, split, None


def dataset_sha(dataset: str) -> str | None:
    from huggingface_hub import HfApi

    info = HfApi().dataset_info(dataset)
    return str(info.sha) if info.sha else None


def run_prediction_benchmark(
    benchmark: str,
    dataset_path: Path,
    prediction_field: str = "prediction",
    answer_field: str = "answer",
    limit: int | None = None,
) -> dict[str, Any]:
    records = load_records(dataset_path)
    if limit is not None:
        records = records[:limit]
    scored: list[dict[str, Any]] = []
    for index, record in enumerate(records):
        prediction = get_nested(record, prediction_field)
        answer = get_nested(record, answer_field)
        if prediction is None or answer is None:
            continue
        score = exact_or_contains_score(str(prediction), str(answer))
        scored.append(
            {
                "index": index,
                "score": score,
                "prediction": str(prediction),
                "answer": str(answer),
            }
        )
    accuracy = sum(item["score"] for item in scored) / len(scored) if scored else 0.0
    return {
        "benchmark": normalize_benchmark_name(benchmark),
        "dataset_path": str(dataset_path),
        "records": len(records),
        "scored": len(scored),
        "metric": "exact_or_contains_accuracy",
        "score": accuracy,
    }


def load_records(path: Path) -> list[dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix == ".jsonl":
        with path.open("r", encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]
    if suffix == ".json":
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f"{path}: cannot read the benchmark file ({error})") from error
        if isinstance(data, list):
            return [dict(item) for item in data if isinstance(item, dict)]
        if isinstance(data, dict):
            for key in ("data", "records", "examples"):
                value = data.get(key)
                if isinstance(value, list):
                    return [dict(item) for item in value if isinstance(item, dict)]
            return [data]
    if suffix == ".parquet":
        import pyarrow.parquet as pq

        return pq.read_table(path).to_pylist()
    raise ValueError(f"Unsupported benchmark dataset format: {path}")










































