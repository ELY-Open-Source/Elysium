# bench — the measurement harness

Everything here measures the product as it is. No arm may read a benchmark gold label.

## run order

```bash
python -m bench.fetch_corpus      # 19 GB of third-party material -> bench/corpus + ~/ely_eye_bench_data
python -m bench.build_sets        # freeze the 6 query sets -> bench/sets/
python -m bench.validate_sets     # schema + gold + scope + modality checks (b-2 gate)
python -m bench.fetch_models      # dense + rerank models used by the ablation arms
python -m bench.ingest_baseline   # the unmodified product ingesting the whole corpus (16 -> 8 workers)
python -m bench.run               # five-arm ablation + latency/scale -> bench/reports/BASELINE.md
python -m pytest bench/tests -q   # metric definitions, hand-computed
```

`bench/runs/` and `bench/corpus/` are gitignored; `bench/corpus/manifest.jsonl` is tracked so the
corpus is reproducible from the manifest alone.

## the arms (b-3)

| arm | what it is |
| --- | --- |
| `bm25_only` | the product's sparse signal alone |
| `dense_only` | the product's dense signal alone (product flag is off today) |
| `graph_only` | the product's graph signal alone — `atom.relations` is never populated, so it is a constant |
| `no_rerank` | the product's exact 0.55 / 0.35 / 0.10 fusion |
| `fusion_rerank` | the same fusion plus a cross-encoder rerank, the upper bound of the current design |

`python -m bench.run` also drives the **unmodified** `RetrievalService.search` over the merged
database and reports its latency plus how far its top-10 differs from the fast BM25 path.

## known environment artifact

pi-lens' pyright reports `Import "bench.sets_common" could not be resolved` (and the same for
`bench.metrics`, `bench.systems`, `elysian.*`, `cv2`, `onnxruntime`, `pypdf.errors`) even though
every one of those imports works. It is not a repo defect:

- `effective_config` on any bench file returns `0 config file(s)` with `resolvedCwd` at the repo
  root, so neither `pyproject.toml [tool.pyright]` nor `pyrightconfig.json` (both of which carry
  `extraPaths: [".", "backend/src"]`) is being read by that runner.
- Runtime proof, run from the repo root with `.venv` active:

```bash
.venv/bin/python -c "import bench.sets_common, bench.metrics, bench.systems, bench.run, bench.ingest_baseline, \
bench.build_mmlongbench, elysian.config, elysian.db, cv2, onnxruntime, pypdf.errors; print('runtime proof OK')"
```

Treat that command as the check of record for import health; treat pyright's *type* findings
(it has caught real defects here: an `AtomRunner` typo, missing `strict=True` on `zip`,
`dict[str, object]` over-narrowing) as separate and worth fixing.

The pi-lens mypy cascade also replays **stale** findings after a fix: it attributes another
file's lines to whichever file was edited last (e.g. `bench/fetch_models.py:107: "object" has
no attribute "encode"`, where line 107 of that file is a `Path` call and the quoted text is
from `bench/systems.py`). The check of record is a fresh-cache run, which has passed on every
current file:

```bash
rm -rf /tmp/mypycache && .venv/bin/python -m mypy --cache-dir /tmp/mypycache bench/   # Success: no issues found
.venv/bin/python -m ruff check bench/                                                  # All checks passed
.venv/bin/python -m pytest bench/tests -q                                              # all green
```

## corpus facts that constrain the numbers

- 50,789 sources / 5,308 queries (2,928 answerable, 2,380 unanswerable), all third-party.
- Video-MME ships mp4s for 129 of 900 videos; the set uses those 129 (387 questions).
- Video-MME has no temporal gold, so its gold region is the whole video — recorded in the set manifest.
- ScreenSpot-v2 boxes are `[x, y, w, h]`, verified against 755 image headers (xywh in bounds 1271/1272).
- CodeSearchNet docstrings appear verbatim inside the code, so the query text is stripped before ingest
  or BM25 gets a free exact match.
- The product keys a source by `{stem[:48]}_{sha256[:16]}`, so identical bytes in two sets collapse to one
  product source; `ingest_report.json` reports `shared_source_ids`.
