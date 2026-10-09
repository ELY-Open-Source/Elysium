"""The auditor must catch planted cheating and stay quiet on honest code."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from bench.audit import (
    best_of_violations,
    frozen_counts,
    injected_cases,
    product_sources,
    report_violations,
    scorer_is_independent,
    third_party_origins,
)

RETRY = """
def collect(proofs, target=0.90):
    while len(proofs) < 3:
        proofs.append(run_once())
        if pass_rate >= target:
            break
"""

HONEST = """
def collect(proofs, limit):
    while len(proofs) < limit:
        proofs.append(next_case())
"""

FULL = {"meta": {"queries": 5308, "answerable": 2928}, "chance": {"recall_at_10": 0.0002}, "arms": [{"arm": "a", "overall": {"recall_at_10": 0.4, "hit_at_10": 0.6, "hit_at_10_wilson_lower": 0.5}}]}


def test_a_loop_that_rerolls_until_a_score_clears_is_a_violation() -> None:
    found = best_of_violations(RETRY, "evals.py")
    assert len(found) == 1
    assert "retry-until-score" in found[0] and "pass_rate" in found[0]


def test_a_plain_data_loop_is_not_flagged() -> None:
    assert best_of_violations(HONEST, "runner.py") == []


def test_the_product_audit_reads_the_package_that_holds_the_proof_suite() -> None:
    sources = product_sources(Path(__file__).resolve().parents[2])
    assert any(path.name == "suite.py" for path in sources), "the auditor must read the real suite"
    for path in sources:
        assert best_of_violations(path.read_text(encoding="utf-8"), path.name) == [], (
            f"{path.name} re-rolls until a score clears"
        )


def test_a_missing_proof_package_is_refused(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="proof suite"):
        product_sources(tmp_path)


def test_an_explicit_best_of_name_is_flagged_wherever_it_appears() -> None:
    assert best_of_violations("best_of_8 = max(scores)", "x.py")
    assert best_of_violations("def until_pass(self): ...", "x.py")


def test_unparseable_source_fails_loudly() -> None:
    with pytest.raises(SystemExit, match="cannot parse"):
        best_of_violations("def broken(:", "broken.py")


def test_a_report_without_a_chance_row_is_refused(tmp_path: Any) -> None:
    path = tmp_path / "baseline.json"
    report = {k: v for k, v in FULL.items() if k != "chance"}
    path.write_text(json.dumps(report), encoding="utf-8")
    found = report_violations(path, frozen_counts())
    assert any("no chance row" in v for v in found)


def test_a_short_run_must_say_which_limit_it_used(tmp_path: Any) -> None:
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps({**FULL, "meta": {"queries": 12, "answerable": 6}}), encoding="utf-8")
    assert any("no --limit is recorded" in v for v in report_violations(path, frozen_counts()))
    limited = {**FULL, "meta": {"queries": 12, "answerable": 6, "limit_per_modality": 2}}
    path.write_text(json.dumps(limited), encoding="utf-8")
    assert report_violations(path, frozen_counts()) == []


def test_a_score_missing_its_wilson_bound_is_refused(tmp_path: Any) -> None:
    path = tmp_path / "baseline.json"
    report = json.loads(json.dumps(FULL))
    del report["arms"][0]["overall"]["hit_at_10_wilson_lower"]
    path.write_text(json.dumps(report), encoding="utf-8")
    assert any("hit_at_10_wilson_lower" in v for v in report_violations(path, frozen_counts()))


def test_an_unreadable_report_is_a_violation_not_a_crash(tmp_path: Any) -> None:
    path = tmp_path / "baseline.json"
    path.write_text("{not json", encoding="utf-8")
    assert any("unreadable report" in v for v in report_violations(path, frozen_counts()))


def test_the_real_scorer_needs_no_model_and_the_real_gold_is_third_party() -> None:
    assert scorer_is_independent() == []
    assert third_party_origins() == []


def test_every_planted_case_is_caught(tmp_path: Any) -> None:
    manifest = frozen_counts()
    for index, (source, expected) in enumerate(injected_cases()):
        if expected[0] == "retry-until-score":
            found = best_of_violations(source, "injected.py")
        else:
            path = tmp_path / f"injected_{index}.json"
            path.write_text(source, encoding="utf-8")
            found = report_violations(path, manifest)
        assert found, f"the auditor accepted {expected[0]}"
        assert expected[0] in found[0], f"{expected[0]} was caught for the wrong reason: {found[0]}"
