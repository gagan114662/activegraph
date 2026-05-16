"""Determinism mode (CONTRACT v0.6 #7).

`deterministic=True` forces temperature=0 and top_p=1, regardless of
what was passed alongside. The Anthropic provider records no seed
(the messages API has no seed parameter). The prompt hash includes
`deterministic` so a determinism-mode and a stochastic-mode prompt
with otherwise-identical content hash differently.
"""

from __future__ import annotations

from activegraph import Graph, Runtime, behavior, llm_behavior
from activegraph.llm.prompt import assemble_prompt
from activegraph.core.view import View

from tests._llm_helpers import Claim, ClaimList, ScriptedProvider


def test_deterministic_forces_temperature_zero_and_top_p_one():
    captured = {}

    class _Cap:
        def complete(self, **kw):
            captured.update(kw)
            return type("R", (), {
                "raw_text": "{}", "parsed": None, "input_tokens": 1,
                "output_tokens": 1, "cost_usd": __import__("decimal").Decimal("0"),
                "latency_seconds": 0.0, "model": kw["model"],
                "finish_reason": "end_turn", "seed": None,
                "cache_hit": False, "provider_meta": {},
                "to_dict": lambda self: {
                    "raw_text": "", "parsed": None, "input_tokens": 1,
                    "output_tokens": 1, "cost_usd": "0", "latency_seconds": 0.0,
                    "model": kw["model"], "finish_reason": "end_turn",
                    "seed": None, "cache_hit": False, "provider_meta": {},
                },
            })()

        def estimate_cost(self, **kw):
            from decimal import Decimal
            return Decimal("0")

        def count_tokens(self, **kw):
            return 1

    @behavior(name="seed", on=["goal.created"])
    def seed(event, graph, ctx):
        graph.add_object("document", {"title": "T", "body": "B"})

    @llm_behavior(
        name="ex",
        on=["object.created"],
        where={"object.type": "document"},
        view={"around": "event.payload.object.id"},
        deterministic=True,
        temperature=0.9,   # ignored under determinism
        top_p=0.5,         # ignored under determinism
    )
    def ex(event, graph, ctx, out):
        pass

    g = Graph()
    Runtime(g, llm_provider=_Cap()).run_goal("g")
    assert captured["temperature"] == 0.0
    assert captured["top_p"] == 1.0


def test_deterministic_flag_is_in_prompt_hash():
    g = Graph()
    obj = g.add_object("doc", {"title": "T", "body": "B"})
    ev = next(e for e in g.events if e.type == "object.created")
    v = View(objects=g.all_objects(), relations=[], events=g.events)
    base = dict(
        behavior_name="x", description="d", model="m",
        output_schema=None, creates=[],
        view=v, event=ev, frame=None,
        around=None, depth=None,
        max_tokens=64, temperature=0.0, top_p=1.0,
    )
    h_det = assemble_prompt(deterministic=True, **base).hash()
    h_stoch = assemble_prompt(deterministic=False, **base).hash()
    assert h_det != h_stoch


def test_seed_field_is_none_for_anthropic():
    """Anthropic's messages API does not expose a seed. The provider
    reflects this honestly — no fake seeds."""

    from activegraph.llm import AnthropicProvider, LLMMessage
    from unittest.mock import MagicMock
    from types import SimpleNamespace

    client = MagicMock()
    client.messages.create.return_value = SimpleNamespace(
        content=[SimpleNamespace(text="ok")],
        usage=SimpleNamespace(input_tokens=1, output_tokens=1),
        model="claude-sonnet-4-5",
        stop_reason="end_turn",
    )
    p = AnthropicProvider(client=client)
    r = p.complete(
        system="", messages=[LLMMessage(role="user", content="hi")],
        model="claude-sonnet-4-5", max_tokens=4, temperature=0.0, top_p=1.0,
        output_schema=None, timeout_seconds=10,
    )
    assert r.seed is None
