"""Download the two retrieval models the ablation needs, into bench/models/.

Both are small on purpose: the benchmark must be runnable on a laptop, and the product's
own 8B embedder is measured separately once it is wired up.

Run: python -m bench.fetch_models
"""

from __future__ import annotations

from pathlib import Path

from huggingface_hub import snapshot_download

from bench.systems import DENSE_MODEL, MODELS, RERANK_MODEL, local_model_dir

WEIGHTS = ["*.safetensors", "*.json", "*.txt", "*.model", "*.tsv", "tokenizer*"]
SKIP = ["onnx/*", "*.onnx", "*.msgpack", "*.h5", "pytorch_model.bin", "tf_model.h5", "*.ot"]


def fetch(repo_id: str) -> Path:
    """Fetch one repo's inference files and report its size."""
    target = local_model_dir(MODELS, repo_id)
    target.mkdir(parents=True, exist_ok=True)
    path = snapshot_download(
        repo_id=repo_id,
        local_dir=str(target),
        allow_patterns=WEIGHTS,
        ignore_patterns=SKIP,
    )
    size = sum(file.stat().st_size for file in Path(path).rglob("*") if file.is_file())
    if size < 1_000_000:
        raise SystemExit(f"{repo_id}: downloaded only {size} bytes to {path}, expected model weights")
    print(f"{repo_id} -> {path} ({size / 1e6:.1f} MB)")
    return Path(path)


def main() -> int:
    fetch(DENSE_MODEL)
    fetch(RERANK_MODEL)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
