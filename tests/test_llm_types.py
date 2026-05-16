"""Smoke tests for LLMMessage / LLMResponse shape contracts (v0.6 #3)."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel

from activegraph.llm import LLMMessage, LLMResponse


def test_message_to_dict_round_shape():
    m = LLMMessage(role="user", content="hello")
    assert m.to_dict() == {"role": "user", "content": "hello"}


def test_response_to_dict_keys_and_decimal_cost_as_string():
    r = LLMResponse(
        raw_text='{"k": 1}',
        parsed={"k": 1},
        input_tokens=10,
        output_tokens=2,
        cost_usd=Decimal("0.001234"),
        latency_seconds=1.5,
        model="claude-sonnet-4-5",
        finish_reason="end_turn",
    )
    d = r.to_dict()
    assert d["cost_usd"] == "0.001234"  # string, not float
    assert d["model"] == "claude-sonnet-4-5"
    assert d["input_tokens"] == 10
    assert d["cache_hit"] is False
    assert d["seed"] is None
    assert d["provider_meta"] == {}


def test_response_pydantic_parsed_dumps_to_dict():
    class Out(BaseModel):
        n: int

    r = LLMResponse(
        raw_text='{"n": 7}',
        parsed=Out(n=7),
        input_tokens=1,
        output_tokens=1,
        cost_usd=Decimal("0"),
        latency_seconds=0.0,
        model="m",
        finish_reason="end_turn",
    )
    assert r.to_dict()["parsed"] == {"n": 7}
