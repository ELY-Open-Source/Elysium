"""recall@10 against 9B tokens per question, log scale, one line per system and one point per arm, as SVG."""

from __future__ import annotations

import math
from html import escape
from pathlib import Path
from typing import Any

WIDTH, HEIGHT = 880, 560
LEFT, RIGHT, TOP, BOTTOM = 76, 40, 112, 84
PAPER, BAND, GRID, INK, MUTED = "#F6F0E4", "#ECE2CF", "#E2D7C2", "#2A2E29", "#6B675C"
COLORS = {"Elysian": "#C4532F", "Mem0": "#3B6EA8"}
LABELS = {
    "elysian": "Elysian",
    "elysian + 9B judge": "Elysian + 9B judge",
    "mem0 raw": "Mem0, raw text",
    "mem0": "Mem0, LLM extraction",
    "mem0 + LLM rerank": "+ its LLM rerank",
}
# Frozen reports keep the arm names they were measured under.
HISTORICAL = {"elysium": "elysian"}
FONT = "Newsreader, 'Iowan Old Style', Georgia, serif"


def nice_ticks(low: float, high: float) -> list[float]:
    """1-2-5 steps between low and high."""
    ticks = []
    for power in range(math.floor(math.log10(low)), math.ceil(math.log10(high)) + 1):
        ticks += [step * 10**power for step in (1, 2, 5) if low <= step * 10**power <= high]
    return ticks


def label(arm: str) -> str:
    first, _, rest = arm.partition(" ")
    return LABELS[" ".join(part for part in (HISTORICAL.get(first, first), rest) if part)]


def compact(tokens: float) -> str:
    return f"{tokens / 1000:,.0f}K"


def marker(system: str, px: float, py: float) -> str:
    color = COLORS[system]
    if system == "Elysian":
        return f'<circle cx="{px:.1f}" cy="{py:.1f}" r="6" fill="{color}" stroke="{PAPER}" stroke-width="2"/>'
    return f'<rect x="{px - 5.5:.1f}" y="{py - 5.5:.1f}" width="11" height="11" rx="1.5" fill="{color}" stroke="{PAPER}" stroke-width="2"/>'


def text(px: float, py: float, body: str, size: int = 13, fill: str = INK, anchor: str = "start", weight: int = 400) -> str:
    return f'<text x="{px:.1f}" y="{py:.1f}" font-size="{size}" fill="{fill}" text-anchor="{anchor}" font-weight="{weight}">{escape(body)}</text>'


def write_chart(payload: dict[str, Any], destination: Path) -> None:
    arms = payload["arms"]
    chance = payload["chance"]["recall_at_10"]
    costs = [row["tokens_per_question"] for row in arms]
    low, high = min(costs) / 2.6, max(costs) * 1.8
    bottom = math.floor(min([row["recall_at_10"] for row in arms] + [chance]) * 10) / 10

    def x(tokens: float) -> float:
        share = (math.log10(tokens) - math.log10(low)) / (math.log10(high) - math.log10(low))
        return LEFT + share * (WIDTH - LEFT - RIGHT)

    def y(recall: float) -> float:
        return TOP + (1 - (recall - bottom) / (1 - bottom)) * (HEIGHT - TOP - BOTTOM)

    floor_y, right = y(bottom), WIDTH - RIGHT
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}" font-family="{FONT}" role="img" aria-labelledby="t d">',
        '<title id="t">recall@10 against 9B tokens per question</title>',
        f'<desc id="d">{payload["questions"]} test questions on one pool; every system uses the same local Qwen3.5-9B. The table is in LIVE.md.</desc>',
        f'<rect width="{WIDTH}" height="{HEIGHT}" fill="{PAPER}"/>',
        text(LEFT, 44, "Same model, same questions: who finds more for less", 22, weight=600),
        text(LEFT, 70, f"recall@10 against 9B tokens per question · {payload['questions']} test questions · one local Qwen3.5-9B for every system", 13, MUTED),
        f'<rect x="{LEFT}" y="{y(chance):.1f}" width="{right - LEFT}" height="{floor_y - y(chance):.1f}" fill="{BAND}"/>',
        text(LEFT + 10, y(chance) + 20, f"below chance · {chance:.3f} · a random ranking of the asker's own pool", 12, MUTED),
    ]
    for step in range(round(bottom * 10), 11):
        py = y(step / 10)
        parts.append(f'<line x1="{LEFT}" y1="{py:.1f}" x2="{right}" y2="{py:.1f}" stroke="{GRID}" stroke-width="1"/>')
        parts.append(text(LEFT - 12, py + 4, f"{step / 10:.1f}", 12, MUTED, "end"))
    for tick in nice_ticks(low, high):
        parts.append(f'<line x1="{x(tick):.1f}" y1="{floor_y}" x2="{x(tick):.1f}" y2="{floor_y + 5}" stroke="{MUTED}" stroke-width="1"/>')
        parts.append(text(x(tick), floor_y + 22, compact(tick), 12, MUTED, "middle"))
    parts.append(f'<line x1="{LEFT}" y1="{floor_y}" x2="{right}" y2="{floor_y}" stroke="{MUTED}" stroke-width="1"/>')
    parts.append(text((LEFT + right) / 2, HEIGHT - 26, "9B tokens per question, log scale: writing the pool shared over the questions, plus asking", 12, MUTED, "middle"))
    parts.append(f'<text x="22" y="{(TOP + floor_y) / 2:.1f}" font-size="12" fill="{MUTED}" text-anchor="middle" transform="rotate(-90 22 {(TOP + floor_y) / 2:.1f})">recall@10</text>')

    best = max((row for row in arms if row["system"] == "Elysian"), key=lambda row: row["recall_at_10"])
    extraction = next(row for row in arms if row["arm"] == "mem0")
    bx, by, ex, ey = x(best["tokens_per_question"]), y(best["recall_at_10"]), x(extraction["tokens_per_question"]), y(extraction["recall_at_10"])
    ratio, gap = extraction["tokens_per_question"] / best["tokens_per_question"], best["recall_at_10"] - extraction["recall_at_10"]
    parts.append(f'<path d="M{bx + 10:.1f},{by:.1f} H{ex:.1f} V{ey - 12:.1f}" fill="none" stroke="{INK}" stroke-width="1" stroke-dasharray="3 4"/>')
    parts.append(text((bx + ex) / 2, by - 10, f"{ratio:.1f}× the tokens", 14, INK, "middle", 600))
    parts.append(text(ex + 10, (by + ey) / 2, f"{gap:.3f} lower recall", 14, INK, "start", 600))

    for system, color in COLORS.items():
        rows = sorted((row for row in arms if row["system"] == system), key=lambda row: row["tokens_per_question"])
        points = [(x(row["tokens_per_question"]), y(row["recall_at_10"])) for row in rows]
        parts.append(f'<polyline fill="none" stroke="{color}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" points="{" ".join(f"{px:.1f},{py:.1f}" for px, py in points)}"/>')
        for (px, py), row in zip(points, rows, strict=True):
            tip = f"{label(row['arm'])}: recall@10 {row['recall_at_10']:.3f}, {row['tokens_per_question']:,.0f} tokens per question"
            parts.append(f"<g><title>{escape(tip)}</title>{marker(system, px, py)}</g>")
    parts += point_labels(arms, x, y, best)

    for index, (system, color) in enumerate(COLORS.items()):
        lx = right - 210 + index * 110
        parts.append(f'<line x1="{lx}" y1="{TOP - 22}" x2="{lx + 26}" y2="{TOP - 22}" stroke="{color}" stroke-width="2"/>')
        parts.append(marker(system, lx + 13, TOP - 22))
        parts.append(text(lx + 34, TOP - 18, system, 13))
    parts.append("</svg>")
    destination.write_text("\n".join(parts) + "\n", encoding="utf-8")


def point_labels(arms: list[dict[str, Any]], x: Any, y: Any, best: dict[str, Any]) -> list[str]:
    """One label per point; stacked points share one; the best sits above its dashed guide; crowded labels flip left."""
    spots = sorted(((x(row["tokens_per_question"]), y(row["recall_at_10"]), row) for row in arms), key=lambda spot: spot[0])
    groups: list[list[tuple[float, float, dict[str, Any]]]] = []
    for spot in spots:
        if groups and abs(groups[-1][0][0] - spot[0]) < 14 and abs(groups[-1][0][1] - spot[1]) < 6:
            groups[-1].append(spot)
        else:
            groups.append([spot])
    out = []
    for group in groups:
        px, py, row = group[0]
        crowded = any(0 < ox - px < 140 and abs(oy - py) < 40 for ox, oy, _ in spots)
        if len(group) > 1:
            slowest = max(spot[2]["p50_seconds"] for spot in group)
            out.append(text(px, py + 28, " ".join(label(spot[2]["arm"]) for spot in group), 13, INK, "middle"))
            out.append(text(px, py + 46, f"{row['recall_at_10']:.3f} · the rerank takes {slowest:.1f} s a question", 13, INK, "middle"))
            continue
        if row is best:
            out.append(text(px, py - 16, f"{label(row['arm'])}  {row['recall_at_10']:.3f}", 14, INK, "middle", 600))
            continue
        side, anchor = (-14, "end") if crowded else (14, "start")
        out.append(text(px + side, py + 4, f"{label(row['arm'])}  {row['recall_at_10']:.3f}", 13, INK, anchor))
    return out
