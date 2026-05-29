"""T7 repeat hard 019 — docstring↔code drift in activegraph.llm.openai._pricing_for.

The function's docstring (activegraph/llm/openai.py:74) promises:

    Unknown models fall back to ``gpt-4o`` pricing.

The Anthropic twin (activegraph/llm/anthropic.py:_pricing_for) documents the
same fallback and explicitly guards it: "the documented fallback must never
raise KeyError", resolving via ``pricing.get(...) or _DEFAULT_PRICING[...]``.

The OpenAI version drifted: on the unknown-model path it does an unconditional
``pricing["gpt-4o"]``. When a caller supplies a *custom* pricing table (the
``pricing=`` constructor argument on OpenAIProvider) that omits the ``gpt-4o``
family key, an unknown model raises ``KeyError`` instead of falling back to
gpt-4o pricing as documented. That gap IS the bug.

This test asserts the DOCUMENTED behavior: an unknown model must resolve to a
(Decimal, Decimal) pricing tuple — the documented gpt-4o fallback — even when
the supplied pricing table omits ``gpt-4o``.
"""

from decimal import Decimal

from activegraph.llm.openai import _DEFAULT_PRICING, _pricing_for


def test_unknown_model_falls_back_to_gpt4o_even_when_custom_table_omits_it():
    # A custom pricing table that does NOT contain the documented fallback key.
    custom = {"gpt-4o-mini": {"input": "0.15", "output": "0.60"}}

    # Documented behavior: unknown models fall back to gpt-4o pricing.
    # The fallback must never raise KeyError (see the Anthropic twin's contract).
    in_price, out_price = _pricing_for("some-unknown-model-xyz", custom)

    assert isinstance(in_price, Decimal)
    assert isinstance(out_price, Decimal)

    # The documented fallback is "gpt-4o pricing". When the custom table omits
    # gpt-4o, the framework's built-in _DEFAULT_PRICING gpt-4o rate is the
    # backstop, exactly as the Anthropic twin does for claude-sonnet-4.
    expected = _DEFAULT_PRICING["gpt-4o"]
    assert in_price == Decimal(str(expected["input"]))
    assert out_price == Decimal(str(expected["output"]))


def test_unknown_model_with_default_table_still_returns_gpt4o():
    # Sanity: the normal path (default table, which DOES carry gpt-4o) keeps
    # working — the fix must not change behavior when the key is present.
    in_price, out_price = _pricing_for("totally-made-up-model", _DEFAULT_PRICING)
    expected = _DEFAULT_PRICING["gpt-4o"]
    assert in_price == Decimal(str(expected["input"]))
    assert out_price == Decimal(str(expected["output"]))
