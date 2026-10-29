"""The judge's score is P(yes) against P(no); a reply with neither is an error, never a zero."""

import math

import httpx
import pytest

from bench import rank_check


def _client(tokens: dict[str, float]) -> httpx.Client:
    top = [{"token": token, "logprob": math.log(chance)} for token, chance in tokens.items()]
    reply = {"choices": [{"logprobs": {"content": [{"top_logprobs": top}]}}]}
    return httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=reply)))


def test_the_score_is_yes_against_no() -> None:
    score = rank_check.judge(_client({"no": 0.6, "yes": 0.2, "The": 0.1}), "http://judge/v1", "m", "q", "doc")

    assert score == pytest.approx(0.25)


def test_a_reply_with_neither_answer_stops_the_run() -> None:
    with pytest.raises(SystemExit, match="neither yes nor no"):
        rank_check.judge(_client({"The": 0.9}), "http://judge/v1", "m", "q", "doc")
