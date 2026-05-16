"""Tool replay semantics. CONTRACT v0.7 tool-determinism decision.

Default: ALL tools (deterministic or not) serve from cache on replay.
Opt-in: `replay_reinvoke_deterministic=True` lets deterministic tools
        re-invoke during replay.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from pydantic import BaseModel

from activegraph import (
    Graph,
    Runtime,
    Tool,
    ToolContext,
    behavior,
    llm_behavior,
    tool,
)
from activegraph.llm import LLMResponse, ToolCall


class _Out(BaseModel):
    text: str


class _In(BaseModel):
    n: int


class _ROut(BaseModel):
    n2: int


_call_count = 0


def _make_tool(*, deterministic: bool):
    """Build a tool whose body increments a counter so we can assert
    re-invocations.
    """
    global _call_count
    _call_count = 0

    @tool(
        name="counter",
        input_schema=_In,
        output_schema=_ROut,
        deterministic=deterministic,
    )
    def counter(args, ctx):
        global _call_count
        _call_count += 1
        return _ROut(n2=args.n * 2)

    from activegraph.tools.decorators import get_tool_registry
    return next(t for t in get_tool_registry() if t.name == "counter")


def _provider_calling_tool_once(tool_name: str = "counter"):
    """Provider that returns one tool_call then one final answer."""
    responses = [
        LLMResponse(
            raw_text="", parsed=None, input_tokens=10, output_tokens=5,
            cost_usd=Decimal("0.001"), latency_seconds=0.1, model="m",
            finish_reason="tool_use",
            tool_calls=[ToolCall(id="c1", name=tool_name, args={"n": 21})],
        ),
        LLMResponse(
            raw_text="", parsed=_Out(text="done"),
            input_tokens=10, output_tokens=5,
            cost_usd=Decimal("0.001"), latency_seconds=0.1, model="m",
            finish_reason="end_turn",
        ),
    ]

    class P:
        def __init__(self):
            self.i = 0

        def complete(self, **kw):
            r = responses[self.i]
            self.i += 1
            return r

        def estimate_cost(self, **kw):
            return Decimal("0.001")

        def count_tokens(self, **kw):
            return 100

    return P()


def _register_seed_and_user(tool_inst: Tool):
    @behavior(name="seed", on=["goal.created"])
    def seed(event, graph, ctx):
        graph.add_object("doc", {"title": "t"})

    @llm_behavior(
        name="ex",
        on=["object.created"],
        where={"object.type": "doc"},
        output_schema=_Out,
        tools=[tool_inst],
    )
    def ex(event, graph, ctx, out):
        pass


def test_replay_serves_non_deterministic_tool_from_cache(tmp_path):
    global _call_count

    db = str(tmp_path / "run.db")
    t = _make_tool(deterministic=False)
    _register_seed_and_user(t)

    rt = Runtime(Graph(), llm_provider=_provider_calling_tool_once(),
                 persist_to=db)
    rt.run_goal("g")
    parent_calls = _call_count
    assert parent_calls == 1

    # Fork with both caches; the tool body should NOT execute again.
    from activegraph import clear_registry, clear_tool_registry
    fork_inst = t  # re-use same Tool object — name lookup is what matters
    _register_seed_and_user(fork_inst)  # idempotent re-registration is fine
    fork = rt.fork(
        at_event=next(e for e in rt.graph.events if e.type == "goal.created").id,
        label="cached",
        replay_llm_cache=True,
        replay_tool_cache=True,
        llm_provider=_provider_calling_tool_once(),
    )
    fork.run_until_idle()
    # Non-deterministic tool, default replay behavior: served from cache.
    assert _call_count == parent_calls  # i.e. still 1
    # And the trace shows the responded event with cache_hit=true.
    tr = [e for e in fork.graph.events if e.type == "tool.responded"]
    assert tr and tr[0].payload.get("cache_hit") is True


def test_replay_serves_deterministic_tool_from_cache_by_default(tmp_path):
    global _call_count

    db = str(tmp_path / "run.db")
    t = _make_tool(deterministic=True)
    _register_seed_and_user(t)

    rt = Runtime(Graph(), llm_provider=_provider_calling_tool_once(),
                 persist_to=db)
    rt.run_goal("g")
    parent_calls = _call_count
    assert parent_calls == 1

    fork = rt.fork(
        at_event=next(e for e in rt.graph.events if e.type == "goal.created").id,
        label="cached",
        replay_llm_cache=True,
        replay_tool_cache=True,
        llm_provider=_provider_calling_tool_once(),
    )
    fork.run_until_idle()
    # Default: even deterministic tools serve from cache on replay.
    assert _call_count == parent_calls


def test_replay_reinvoke_deterministic_actually_reinvokes(tmp_path):
    global _call_count

    db = str(tmp_path / "run.db")
    t = _make_tool(deterministic=True)
    _register_seed_and_user(t)

    rt = Runtime(Graph(), llm_provider=_provider_calling_tool_once(),
                 persist_to=db)
    rt.run_goal("g")
    parent_calls = _call_count
    assert parent_calls == 1

    fork = rt.fork(
        at_event=next(e for e in rt.graph.events if e.type == "goal.created").id,
        label="rerun",
        replay_llm_cache=True,
        replay_tool_cache=True,
        replay_reinvoke_deterministic=True,
        llm_provider=_provider_calling_tool_once(),
    )
    fork.run_until_idle()
    # Opt-in re-invoke: deterministic tool runs again in the fork.
    assert _call_count == parent_calls + 1
