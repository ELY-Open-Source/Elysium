"""Render a proof report as one row per claim, verdict first.

A JSON report hides the shape of the evidence: a deferred claim and a passed claim look equally
short. The table puts the counts on the first line and the reason under every claim that did not
pass, so nobody reads an unrun claim as a proven one.
"""

from __future__ import annotations

from ..evaluation_schemas import ProofSuiteReport

STATUS_ORDER = ("failed", "passed", "deferred", "removed")


def render_table(report: ProofSuiteReport) -> str:
    counts: dict[str, int] = {status: 0 for status in STATUS_ORDER}
    for check in report.checks:
        counts[check.status] = counts.get(check.status, 0) + 1
    lines = [
        f"proof {report.proof_id} · cartridge {report.cartridge_id} · suite {report.status}",
        "counts: " + ", ".join(f"{status} {counts.get(status, 0)}" for status in STATUS_ORDER),
        "",
    ]
    for status in STATUS_ORDER:
        for check in report.checks:
            if check.status != status:
                continue
            lines.append(f"[{check.status:^7}] {check.name}")
            lines.append(f"          ran: {check.detail}")
            if check.reason:
                lines.append(f"          why: {check.reason}")
            if check.rerun:
                lines.append(f"          rerun: {check.rerun}")
    return "\n".join(lines)
