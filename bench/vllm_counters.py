"""Tokens a served vLLM spent between two readings of its /metrics; no client has to report its own usage."""

from __future__ import annotations

import httpx

NAMES = ("vllm:prompt_tokens_total", "vllm:generation_tokens_total")


def counters(base_url: str) -> dict[str, float]:
    """The cumulative prompt and generated token counts of the server behind `base_url` (a /v1 URL)."""
    text = httpx.get(base_url.removesuffix("/v1") + "/metrics", timeout=10).text
    found = {name: 0.0 for name in NAMES}
    seen = set()
    for line in text.splitlines():
        name = line.split("{", 1)[0].split(" ", 1)[0]
        if name in found:
            found[name] += float(line.rsplit(" ", 1)[1])
            seen.add(name)
    missing = sorted(set(NAMES) - seen)
    if missing:
        raise SystemExit(f"{base_url} exposes no {missing}; this cost is read from vLLM's counters")
    return found


def spent(before: dict[str, float], after: dict[str, float]) -> dict[str, int]:
    return {
        "prompt": int(after["vllm:prompt_tokens_total"] - before["vllm:prompt_tokens_total"]),
        "generated": int(after["vllm:generation_tokens_total"] - before["vllm:generation_tokens_total"]),
    }
