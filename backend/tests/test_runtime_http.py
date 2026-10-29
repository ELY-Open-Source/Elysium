"""The served-model path asks for an answer directly, and an answer it never reached is an error.

Qwen3.5 thinks before it answers and the thinking spends the same token budget; measured on a
screenshot, a 512-token budget ended in finish_reason "length" with content null, and the product
returned that as a successful generation with no text.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest

import elysium.runtime as runtime_module
from elysium.config import Settings
from elysium.runtime import QwenRuntime, RuntimeUnavailableError


def _serve(monkeypatch: pytest.MonkeyPatch, reply: dict[str, Any], sent: list[dict[str, Any]]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        import json

        sent.append(json.loads(request.content))
        return httpx.Response(200, json=reply)

    real = httpx.Client
    monkeypatch.setattr(runtime_module.httpx, "Client", lambda **kwargs: real(transport=httpx.MockTransport(handler), **kwargs))


def _runtime(tmp_path: Path) -> QwenRuntime:
    return QwenRuntime(Settings(home=tmp_path, runtime_backend="sglang", sglang_base_url="http://127.0.0.1:8001/v1"))


def test_the_request_asks_for_the_answer_without_thinking(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[dict[str, Any]] = []
    _serve(monkeypatch, {"choices": [{"message": {"content": "Paris."}, "finish_reason": "stop"}]}, sent)

    generation = _runtime(tmp_path).generate_prompt("What is the capital of France?")

    assert generation.text == "Paris."
    assert sent[0]["chat_template_kwargs"] == {"enable_thinking": False}


def test_a_budget_spent_before_any_answer_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[dict[str, Any]] = []
    _serve(monkeypatch, {"choices": [{"message": {"content": None, "reasoning": "..."}, "finish_reason": "length"}]}, sent)

    with pytest.raises(RuntimeUnavailableError, match="no answer \\(finish_reason 'length' after 512 tokens\\)"):
        _runtime(tmp_path).generate_prompt("Describe this screenshot.")
