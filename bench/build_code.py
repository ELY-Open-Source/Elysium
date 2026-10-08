"""Build code sets from CodeSearchNet.

A function's docstring is the query and the function itself is the answer, so
the gold is the dataset's own (func_path_in_repository, func_name) pair. Two
hazards are handled explicitly: the published function text still contains its
docstring, which would hand BM25 a free exact match, and 672 docstrings are
shared by more than one function, which makes their gold ambiguous. Whole
repository clones are a b-5 concern, not part of this set.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
import warnings
from pathlib import Path
from typing import Any

from pyarrow.parquet import ParquetFile

from bench.corpus_sources import source_for
from bench.sets_common import (
    DATA_ROOT,
    SETS,
    corpus_path,
    corpus_record,
    query_record,
    safe_id,
    safe_segment,
    sample_by_holder,
    write_jsonl,
)

DATASET = "code-search-net/code_search_net"
SOURCE = source_for(DATASET)
REVISION = str(SOURCE["revision"])
SNAPSHOT_AT = str(SOURCE["snapshot_at"])
PARQUET = "python/test-00000-of-00001.parquet"
SCENARIO = "code-search"
HELD_OUT_BUCKET = 15


def strip_docstring(code: str) -> tuple[str, bool]:
    """Remove a function's own docstring lines; report whether that succeeded."""
    try:
        with warnings.catch_warnings():
            # Corpus code is third-party; its own escape sequences are not our problem.
            warnings.simplefilter("ignore", SyntaxWarning)
            tree = ast.parse(code)
    except (SyntaxError, ValueError):
        return code, False
    body = tree.body
    if len(body) == 1 and isinstance(body[0], ast.FunctionDef | ast.AsyncFunctionDef):
        body = body[0].body
    if not body or not isinstance(body[0], ast.Expr):
        return code, False
    first = body[0]
    value = first.value
    if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
        return code, False
    lines = code.splitlines(keepends=True)
    start, end = first.lineno - 1, first.end_lineno
    stripped = "".join(lines[:start] + lines[end:])
    if not stripped.strip():
        return code, False
    return stripped, True


def normalize_docstring(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def repo_slug(repository: str) -> str:
    """CodeSearchNet names are 'owner/name'; one safe form is used as holder and path."""
    return safe_id(repository.replace("/", "-"), f"repository_name {repository!r}")


def function_path(repository: str, func_path: str, func_name: str, tag: str) -> str:
    """Where the function text lives under DATA_ROOT, mirroring the repo layout.

    The tag keeps two paths that sanitize alike, or one file holding two functions
    with the same name, from overwriting each other.
    """
    segments = [repo_slug(repository)]
    segments += [
        safe_segment(segment, f"func_path_in_repository {func_path!r}")
        for segment in func_path.split("/")
        if segment not in ("", ".")
    ]
    stem = segments[-1].removesuffix(".py") or "module"
    segments[-1] = f"{stem}-{tag}"
    return (Path("codesearchnet") / Path(*segments)).with_suffix(".py").as_posix()


def read_rows() -> list[dict[str, Any]]:
    table = ParquetFile(corpus_path(DATASET, PARQUET)).read()
    return table.select(
        ["repository_name", "func_path_in_repository", "func_name", "func_code_string",
         "func_documentation_string", "func_code_url"]
    ).to_pylist()


def build_functions() -> tuple[list, list[dict[str, Any]], dict]:
    rows = read_rows()
    corpus: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    skipped = {"no_docstring": 0, "empty_after_strip": 0, "docstring_left_in_text": 0}

    for index, row in enumerate(rows):
        repository = str(row["repository_name"])
        func_path = str(row["func_path_in_repository"])
        func_name = str(row["func_name"])
        code = str(row["func_code_string"])
        docstring = str(row["func_documentation_string"]).strip()
        if not docstring or not code.strip():
            skipped["no_docstring"] += 1
            continue
        stripped, removed = strip_docstring(code)
        if not removed and normalize_docstring(docstring) in normalize_docstring(stripped):
            skipped["docstring_left_in_text"] += 1
            continue
        if not stripped.strip():
            skipped["empty_after_strip"] += 1
            continue
        # One dataset row is one function; its index is the only unique identity, because a file may define the same name twice.
        tag = hashlib.sha256(f"{func_path}#{func_name}#{index}".encode()).hexdigest()[:10]
        relative = function_path(repository, func_path, func_name, tag)
        target = DATA_ROOT / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(stripped, encoding="utf-8")
        source_id = f"csn:{repository}:{func_path}:{func_name}#{index}"
        corpus.append(
            corpus_record(
                source_id=source_id,
                modality="code",
                path=relative,
                title=f"{func_path}:{func_name}",
                observed_at=SNAPSHOT_AT,
                holder=repo_slug(repository),
                scenario=SCENARIO,
                root="derived",
            )
        )
        candidates.append(
            {
                "source_id": source_id,
                "repository": repo_slug(repository),
                "handle": f"{func_name}-{tag}",
                "url": str(row["func_code_url"]),
                "docstring": docstring,
                "key": normalize_docstring(docstring),
                "region": {"path": func_path, "symbol": func_name},
                "held_out": int(hashlib.sha256(source_id.encode()).hexdigest(), 16) % 100
                < HELD_OUT_BUCKET,
            }
        )

    keys: dict[str, int] = {}
    for candidate in candidates:
        keys[candidate["key"]] = keys.get(candidate["key"], 0) + 1
    ambiguous = sum(1 for candidate in candidates if keys[candidate["key"]] > 1)
    return corpus, candidates, {
        "functions_in_split": len(rows),
        "functions_kept": len(candidates),
        "skipped": skipped,
        "ambiguous_docstrings_dropped": ambiguous,
        "held_out_share": HELD_OUT_BUCKET,
    }


def to_query(candidate: dict[str, Any], unanswerable: bool) -> dict[str, Any]:
    """Turn one CodeSearchNet function into a docstring-to-code query."""
    suffix = "" if not unanswerable else "@held-out"
    origin = {
        "dataset": DATASET,
        "revision": REVISION,
        "item": f"url:{candidate['url']}",
    }
    if unanswerable:
        origin["construction"] = "held-out function"
    return query_record(
        query_id=f"csn:{candidate['repository']}:{candidate['handle']}{suffix}",
        modality="code",
        question=candidate["docstring"],
        answer=None if unanswerable else candidate["source_id"],
        answer_format="code",
        gold=[] if unanswerable else [{"source_id": candidate["source_id"], "region": candidate["region"]}],
        holder=candidate["repository"],
        scenario=SCENARIO,
        as_of=SNAPSHOT_AT,
        origin=origin,
    )


def build() -> tuple[list, list, dict]:
    corpus, candidates, stats = build_functions()
    answerable = sample_by_holder(
        [to_query(c, False) for c in candidates if not c["held_out"]], per_holder=2
    )
    unanswerable = [to_query(c, True) for c in candidates if c["held_out"]]
    queries = answerable + unanswerable[: len(answerable)]

    report = stats | {
        "datasets": [DATASET],
        "revision": REVISION,
        "holders": sorted({record["holder"] for record in corpus}),
        "queries": len(queries),
        "queries_answerable": len(answerable),
        "queries_held_out_unanswerable": len(queries) - len(answerable),
    }
    return corpus, queries, report


def main() -> None:
    corpus, queries, report = build()
    corpus_count, corpus_sha = write_jsonl(SETS / "corpus" / "code.jsonl", corpus)
    _query_count, query_sha = write_jsonl(SETS / "code.jsonl", queries)
    report |= {"corpus_records": corpus_count, "corpus_sha256": corpus_sha, "queries_sha256": query_sha}
    (SETS / "reports").mkdir(parents=True, exist_ok=True)
    (SETS / "reports" / "code.json").write_text(
        json.dumps(report, indent=1, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps(report, indent=1, sort_keys=True))


if __name__ == "__main__":
    main()
