"""recall@10 against 9B tokens per question, log scale, one line per system and one point per arm, as SVG."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

WIDTH, HEIGHT = 760, 480
LEFT, RIGHT, TOP, BOTTOM = 70, 190, 30, 60
COLORS = {"Elysium": "#2a6fdb", "Mem0": "#d9822b"}


def write_chart(payload: dict[str, Any], destination: Path) -> None:
    arms = payload["arms"]
    costs = [row["tokens_per_question"] for row in arms]
    low = 10 ** math.floor(math.log10(min(costs)))
    high = 10 ** math.ceil(math.log10(max(costs)))
    chance = payload["chance"]["recall_at_10_pool"]
    bottom = math.floor(min([row["recall_at_10"] for row in arms] + [chance]) * 10) / 10

    def x(tokens: float) -> float:
        share = (math.log10(tokens) - math.log10(low)) / (math.log10(high) - math.log10(low))
        return LEFT + share * (WIDTH - LEFT - RIGHT)

    def y(recall: float) -> float:
        return TOP + (1 - (recall - bottom) / (1 - bottom)) * (HEIGHT - TOP - BOTTOM)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" font-family="sans-serif" font-size="12">',
        f'<rect width="{WIDTH}" height="{HEIGHT}" fill="white"/>',
        f'<text x="{LEFT}" y="18" font-size="14">recall@10 against 9B tokens per question ({payload["questions"]} test questions, one pool)</text>',
    ]
    for power in range(round(math.log10(low)), round(math.log10(high)) + 1):
        px = x(10**power)
        label = f"{10**power:,}"
        parts.append(f'<line x1="{px:.1f}" y1="{TOP}" x2="{px:.1f}" y2="{HEIGHT - BOTTOM}" stroke="#e5e5e5"/>')
        parts.append(f'<text x="{px:.1f}" y="{HEIGHT - BOTTOM + 16}" text-anchor="middle">{label}</text>')
    for step in range(round(bottom * 10), 11):
        py = y(step / 10)
        parts.append(f'<line x1="{LEFT}" y1="{py:.1f}" x2="{WIDTH - RIGHT}" y2="{py:.1f}" stroke="#e5e5e5"/>')
        parts.append(f'<text x="{LEFT - 8}" y="{py + 4:.1f}" text-anchor="end">{step / 10:.1f}</text>')
    parts.append(f'<line x1="{LEFT}" y1="{y(chance):.1f}" x2="{WIDTH - RIGHT}" y2="{y(chance):.1f}" stroke="#888" stroke-dasharray="4 4"/>')
    parts.append(f'<text x="{WIDTH - RIGHT + 6}" y="{y(chance) + 4:.1f}" fill="#666">chance {chance:.3f}</text>')
    parts.append(f'<text x="{(LEFT + WIDTH - RIGHT) / 2}" y="{HEIGHT - 18}" text-anchor="middle">9B tokens per question (writing amortized over the questions, plus asking), log scale</text>')
    parts.append(f'<text x="18" y="{(TOP + HEIGHT - BOTTOM) / 2}" text-anchor="middle" transform="rotate(-90 18 {(TOP + HEIGHT - BOTTOM) / 2})">recall@10</text>')
    for index, (system, color) in enumerate(COLORS.items()):
        rows = sorted((row for row in arms if row["system"] == system), key=lambda row: row["tokens_per_question"])
        points = [(x(row["tokens_per_question"]), y(row["recall_at_10"])) for row in rows]
        parts.append('<polyline fill="none" stroke-width="2" stroke="{}" points="{}"/>'.format(color, " ".join(f"{px:.1f},{py:.1f}" for px, py in points)))
        for (px, py), row in zip(points, rows, strict=True):
            parts.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="4.5" fill="{color}"/>')
            parts.append(f'<text x="{px + 7:.1f}" y="{py - 7:.1f}" fill="{color}">{row["arm"]} {row["recall_at_10"]:.3f}</text>')
        parts.append(f'<rect x="{WIDTH - RIGHT + 6}" y="{TOP + 20 * index}" width="12" height="12" fill="{color}"/>')
        parts.append(f'<text x="{WIDTH - RIGHT + 24}" y="{TOP + 20 * index + 11}">{system}</text>')
    parts.append("</svg>")
    destination.write_text("\n".join(parts) + "\n", encoding="utf-8")
