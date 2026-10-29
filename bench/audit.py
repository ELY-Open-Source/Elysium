"""b-5: the audit that trusts nothing we wrote, including this file.

Four rules, each machine-checked:

1. single_attempt  - no loop may re-roll a case until a score target clears (best-of-N).
2. full_n          - a frozen score must cover the frozen n, or say which --limit it used.
3. chance_row      - every scored arm or store sits next to the score random guessing gets.
4. producer_verifier - gold labels name third-party datasets, and the scorer imports no model.

Run: python -m bench.audit                 # audit the repo and the reports
     python -m bench.audit --self-test     # prove the auditor catches injected cheating
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path
from typing import Any

from bench.sets_common import MODALITIES, SETS

ROOT = Path(__file__).resolve().parent
REPORTS = ROOT / "reports"
CORPUS_MANIFEST = ROOT / "corpus" / "manifest.jsonl"

# Words that only appear where a score is compared to a target; a loop that re-rolls until one clears is best-of-N whatever it is called.
SCORE_WORDS = ("pass_rate", "pass_target", "accuracy", "recall", "hit_rate", "score", "target")
RETRY_MARKERS = ("best_of", "bestof", "reroll", "re_roll", "until_pass", "retry_until")
# The scorer must stay a pure function of (query, ranked ids, gold ids), or the thing being graded starts grading itself.
SCORER_FORBIDDEN = ("elysium", "transformers", "sentence_transformers", "torch", "bench.systems", "bench.counterpart")
FROZEN_REPORTS = ("baseline.json", "baseline_external.json", "video_audio.json")


def _words_in(node: ast.AST) -> set[str]:
    """Score vocabulary reachable from one expression, by name or attribute."""
    found: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name | ast.Attribute | ast.Constant):
            text = str(getattr(child, "attr", None) or getattr(child, "id", None) or getattr(child, "value", ""))
            text = text.lower()
            found.update(word for word in SCORE_WORDS if word in text)
    return found


def best_of_violations(source: str, name: str) -> list[str]:
    """Flag re-rolling: a while-loop that breaks on a score comparison, or an explicit best-of marker."""
    try:
        tree = ast.parse(source, filename=str(name))
    except SyntaxError as error:
        raise SystemExit(f"{name}: cannot parse ({error})") from error
    violations: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.While):
            continue
        loop_words = _words_in(node.test)
        break_words: set[str] = set()
        for inner in ast.walk(node):
            if isinstance(inner, ast.Break):
                for parent in _enclosing_tests(inner, node):
                    break_words |= _words_in(parent)
        if loop_words or break_words:
            words = ", ".join(sorted(loop_words | break_words))
            violations.append(f"{name}:{node.lineno}: retry-until-score loop re-rolls on {words}")
    for node in ast.walk(tree):
        if isinstance(node, ast.Name | ast.Attribute | ast.keyword):
            text = str(getattr(node, "attr", None) or getattr(node, "id", None) or getattr(node, "arg", "")).lower()
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            text = node.name.lower()  # a function called collect_until_pass is the same trick
        else:
            continue
        if any(marker in text for marker in RETRY_MARKERS):
            violations.append(f"{name}:{node.lineno}: {text!r} re-rolls until a target")
    return violations


def _enclosing_tests(break_node: ast.Break, loop: ast.While) -> list[ast.expr]:
    """Tests guarding this break between it and the loop head; a bare break counts as the loop test."""
    tests: list[ast.expr] = []
    for node in ast.walk(loop):
        if isinstance(node, ast.If) and any(child is break_node for child in node.body):
            tests.append(node.test)
    return tests or [loop.test]


def audit_sources(paths: list[Path]) -> list[str]:
    """Rule 1 over our own harness: the benchmark code may never re-roll a query."""
    violations: list[str] = []
    for path in paths:
        violations.extend(best_of_violations(path.read_text(encoding="utf-8"), str(path.relative_to(ROOT.parent))))
    return violations


def frozen_counts() -> dict[str, Any]:
    """The n every frozen report is required to cover."""
    path = SETS / "manifest.json"
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SystemExit(f"{path}: cannot read the frozen set manifest ({error})") from error
    missing = [key for key in ("queries", "queries_answerable", "modalities") if key not in manifest]
    if missing:
        raise SystemExit(f"{path}: manifest is missing {missing}")
    return manifest


def report_violations(path: Path, manifest: dict[str, Any]) -> list[str]:
    """Rules 2 and 3 over one report: full n, and a chance row beside every score."""
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return [f"{path.name}: unreadable report ({error})"]
    violations: list[str] = []
    meta = report.get("meta", {})
    if (
        (meta.get("queries") != manifest["queries"] or meta.get("answerable") != manifest["queries_answerable"])
        and not meta.get("limit_per_modality")
    ):
        violations.append(
            f"{path.name}: scored {meta.get('queries')}/{meta.get('answerable')} queries but the frozen set "
            f"is {manifest['queries']}/{manifest['queries_answerable']} and no --limit is recorded"
        )
    chance = report.get("chance")
    if chance is None:
        violations.append(f"{path.name}: no chance row, so no score in it can be read as signal")
    scored = report.get("arms") or report.get("stores") or []
    if not scored:
        violations.append(f"{path.name}: no arms or stores scored")
    for entry in scored:
        name = entry.get("arm") or entry.get("store") or "?"
        overall = entry.get("overall") or {}
        for key in ("recall_at_10", "hit_at_10", "hit_at_10_wilson_lower"):
            if key not in overall:
                violations.append(f"{path.name}: {name} is missing {key}")
        if chance is not None and overall.get("recall_at_10") is not None and chance.get("recall_at_10") is None:
            violations.append(f"{path.name}: chance row has no recall_at_10 to compare {name} against")
    return violations


def scorer_is_independent() -> list[str]:
    """Rule 4a: the scorer is a pure function of ids, so it cannot share the question's generation."""
    path = ROOT / "metrics.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    violations: list[str] = []
    for node in ast.walk(tree):
        modules: list[str] = []
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules = [node.module]
        line = getattr(node, "lineno", 0)
        for module in modules:
            if any(module == banned or module.startswith(f"{banned}.") for banned in SCORER_FORBIDDEN):
                violations.append(f"bench/metrics.py:{line}: imports {module}, which the scorer must not need")
    return violations


def third_party_origins() -> list[str]:
    """Rule 4b: every gold label must name a dataset we downloaded, at the revision we froze."""
    datasets: dict[str, str] = {}
    try:
        lines = CORPUS_MANIFEST.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise SystemExit(f"{CORPUS_MANIFEST}: cannot read the corpus manifest ({error})") from error
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
            datasets[str(record["dataset"])] = str(record["revision"])
        except (json.JSONDecodeError, KeyError) as error:
            raise SystemExit(f"{CORPUS_MANIFEST}:{number}: unreadable record ({error})") from error
    if not datasets:
        raise SystemExit(f"{CORPUS_MANIFEST}: names no dataset")
    violations: list[str] = []
    for modality in MODALITIES:
        path = SETS / f"{modality}.jsonl"
        if not path.is_file():
            violations.append(f"{path}: missing set file")
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                raise SystemExit(f"{path}:{number}: unreadable record ({error})") from error
            origin = record.get("origin") or {}
            dataset = str(origin.get("dataset", ""))
            if dataset not in datasets:
                violations.append(f"bench/sets/{modality}.jsonl:{number}: origin {dataset!r} is not a frozen dataset")
            elif origin.get("revision") != datasets[dataset]:
                violations.append(
                    f"bench/sets/{modality}.jsonl:{number}: {dataset} is cited at revision "
                    f"{origin.get('revision')}, frozen at {datasets[dataset]}"
                )
    return violations


def injected_cases() -> list[tuple[str, list[str]]]:
    """Cheating we plant on purpose; the auditor must refuse each one."""
    best_of_n = (
        "def collect(proofs):\n"
        "    while len(proofs) < 3:\n"
        "        proofs.append(run_once())\n"
        "        if pass_rate >= target:\n"
        "            break\n"
    )
    no_chance = {"meta": {"queries": 5308, "answerable": 2928}, "arms": [{"arm": "x", "overall": {}}]}
    return [(best_of_n, ["retry-until-score"]), (json.dumps(no_chance), ["no chance row"])]


def self_test(manifest: dict[str, Any]) -> int:
    """Prove the auditor catches the injected cases; a rule that catches nothing is not a rule."""
    failures = 0
    for source, expected in injected_cases():
        if expected[0] == "retry-until-score":
            found = best_of_violations(source, "injected.py")
        else:
            path = Path("injected_report.json")
            path.write_text(source, encoding="utf-8")
            found = report_violations(path, manifest)
            path.unlink()
        if not found:
            print(f"SELF-TEST FAIL: the auditor accepted an injected case ({expected[0]})")
            failures += 1
        else:
            print(f"self-test ok: caught {expected[0]} -> {found[0]}")
    return failures


def product_sources(root: Path) -> list[Path]:
    """The product's proof suite, wherever it lives now: it moved out of one evals.py into a package."""
    package = root / "backend" / "src" / "elysium" / "proofs"
    if not package.is_dir():
        raise SystemExit(f"{package}: --product asked for the proof suite but it is not there")
    sources = sorted(package.glob("*.py"))
    if not sources:
        raise SystemExit(f"{package}: the proof suite holds no python file")
    return sources


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--self-test", action="store_true", help="check the auditor against injected cheating")
    parser.add_argument("--product", action="store_true", help="also audit the product's proof suite for re-rolling")
    args = parser.parse_args()

    manifest = frozen_counts()
    if args.self_test:
        return 1 if self_test(manifest) else 0

    sources = [
        path
        for path in sorted(ROOT.rglob("*.py"))
        if "tests" not in path.parts and "corpus" not in path.parts and path.name != "audit.py"
    ]
    violations = audit_sources(sources)
    if args.product:
        for path in product_sources(ROOT.parent):
            name = str(path.relative_to(ROOT.parent))
            violations.extend(best_of_violations(path.read_text(encoding="utf-8"), name))

    for name in FROZEN_REPORTS:
        path = REPORTS / name
        if path.is_file():
            violations.extend(report_violations(path, manifest))
        else:
            violations.append(f"{path}: frozen report missing")
    violations.extend(scorer_is_independent())
    violations.extend(third_party_origins())

    print(f"audited {len(sources)} harness files, {len(FROZEN_REPORTS)} reports, {len(MODALITIES)} set files")
    if violations:
        for violation in violations:
            print(f"VIOLATION: {violation}", file=sys.stderr)
        print(f"{len(violations)} violation(s)", file=sys.stderr)
        return 1
    print("clean: single attempt, full n, chance rows present, producer is not verifier")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
