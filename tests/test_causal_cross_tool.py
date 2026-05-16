"""Causal chain crosses tool boundaries. CONTRACT v0.7 #19.

Objects created inside an LLM behavior handler that used tools carry
`tool_request_event_ids` in their provenance. `trace.causal_chain`
walks through every tool call in addition to the LLM call.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel

from activegraph import (
    Graph,
    Runtime,
    behavior,
    llm_behavior,
    tool,
)
from activegraph.llm import LLMResponse, ToolCall


class _Out(BaseModel):
    text: str


class _ToolIn(BaseModel):
    q: str


class _ToolOut(BaseModel):
    ok: bool


class _Provider:
    def __init__(self):
        self._responses = [
            LLMResponse(
                raw_text="", parsed=None, input_tokens=1, output_tokens=1,
                cost_usd=Decimal("0.001"), latency_seconds=0.1, model="m",
                finish_reason="tool_use",
                tool_calls=[ToolCall(id="c1", name="t1", args={"q": "x"})],
            ),
            LLMResponse(
                raw_text="", parsed=None, input_tokens=1, output_tokens=1,
                cost_usd=Decimal("0.001"), latency_seconds=0.1, model="m",
                finish_reason="tool_use",
                tool_calls=[ToolCall(id="c2", name="t2", args={"q": "y"})],
            ),
            LLMResponse(
                raw_text="", parsed=_Out(text="done"),
                input_tokens=1, output_tokens=1,
                cost_usd=Decimal("0.001"), latency_seconds=0.1, model="m",
                finish_reason="end_turn",
            ),
        ]
        self.i = 0

    def complete(self, **kw):
        r = self._responses[self.i]
        self.i += 1
        return r

    def estimate_cost(self, **kw):
        return Decimal("0.001")

    def count_tokens(self, **kw):
        return 100


def test_provenance_carries_tool_request_event_ids():
    @tool(name="t1", input_schema=_ToolIn, output_schema=_ToolOut, deterministic=True)
    def t1(args, ctx):
        return _ToolOut(ok=True)

    @tool(name="t2", input_schema=_ToolIn, output_schema=_ToolOut, deterministic=True)
    def t2(args, ctx):
        return _ToolOut(ok=True)

    @behavior(name="seed", on=["goal.created"])
    def seed(event, graph, ctx):
        graph.add_object("doc", {"title": "t"})

    @llm_behavior(
        name="ex",
        on=["object.created"],
        where={"object.type": "doc"},
        output_schema=_Out,
        tools=[t1, t2],
    )
    def ex(event, graph, ctx, out):
        graph.add_object("result", {"text": out.text})

    g = Graph()
    Runtime(g, llm_provider=_Provider()).run_goal("g")

    result = next(o for o in g.all_objects() if o.type == "result")
    assert "tool_request_event_ids" in result.provenance
    assert len(result.provenance["tool_request_event_ids"]) == 2
    assert "llm_request_event_id" in result.provenance


def test_causal_chain_renders_llm_and_tool_calls():
    @tool(name="t1", input_schema=_ToolIn, output_schema=_ToolOut, deterministic=True)
    def t1(args, ctx):
        return _ToolOut(ok=True)

    @tool(name="t2", input_schema=_ToolIn, output_schema=_ToolOut, deterministic=True)
    def t2(args, ctx):
        return _ToolOut(ok=True)

    @behavior(name="seed", on=["goal.created"])
    def seed(event, graph, ctx):
        graph.add_object("doc", {"title": "t"})

    @llm_behavior(
        name="ex",
        on=["object.created"],
        where={"object.type": "doc"},
        output_schema=_Out,
        tools=[t1, t2],
    )
    def ex(event, graph, ctx, out):
        graph.add_object("result", {"text": out.text})

    g = Graph()
    rt = Runtime(g, llm_provider=_Provider())
    rt.run_goal("g")
    result = next(o for o in g.all_objects() if o.type == "result")
    chain = rt.trace.causal_chain(result.id)
    # llm.requested + llm.responded
    assert "llm.requested" in chain
    assert "llm.responded" in chain
    # both tools appear
    assert "tool=t1" in chain
    assert "tool=t2" in chain
    # walks all the way to goal.created
    assert "goal.created" in chain
