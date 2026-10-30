"""The cost chart draws from the frozen report as it was measured, old arm names included."""

import json
from pathlib import Path

from bench.live_chart import write_chart


def test_the_frozen_live_report_draws(tmp_path: Path) -> None:
    payload = json.loads(Path("bench/reports/live.json").read_text(encoding="utf-8"))
    assert {row["arm"].split(" ")[0] for row in payload["arms"]} == {"elysium", "mem0"}

    write_chart(payload, tmp_path / "chart.svg")

    svg = (tmp_path / "chart.svg").read_text(encoding="utf-8")
    assert "Elysian + 9B judge  0.909" in svg
    assert "7.0× the tokens" in svg
    assert "0.191 lower recall" in svg
