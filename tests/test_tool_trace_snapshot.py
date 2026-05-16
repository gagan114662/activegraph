"""Snapshot test for the v0.7 tool + pattern trace. CONTRACT v0.7 #18.

The `[tool.requested]`, `[tool.responded]`, `[pattern.matched]`,
`[behavior.scheduled]` lines are part of the public trace format. This
is the canary for any drift.
"""

from __future__ import annotations

import os
from decimal import Decimal

from pydantic import BaseModel

from activegraph import (
    FrozenClock,
    Graph,
    IDGen,
    Runtime,
    behavior,
    llm_behavior,
    tool,
)
from activegraph.llm import LLMResponse, ToolCall


SNAPSHOT_PATH = os.path.join(
    os.path.dirname(__file__), "snapshots", "tool_trace.txt"
)


class _Out(BaseModel):
    text: str


class _ToolIn(BaseModel):
    q: str


class _ToolOut(BaseModel):
    answer: str


class _Provider:
    def __init__(self):
        self._responses = [
            LLMResponse(
                raw_text="",
                parsed=None,
                input_tokens=120,
                output_tokens=24,
                cost_usd=Decimal("0.0012"),
                latency_seconds=0.5,
                model="claude-sonnet-4-5",
                finish_reason="tool_use",
                tool_calls=[ToolCall(id="c1", name="my_tool", args={"q": "hi"})],
            ),
            LLMResponse(
                raw_text="",
                parsed=_Out(text="ok"),
                input_tokens=120,
                output_tokens=24,
                cost_usd=Decimal("0.0012"),
                latency_seconds=0.5,
                model="claude-sonnet-4-5",
                finish_reason="end_turn",
            ),
        ]
        self.i = 0

    def complete(self, **kw):
        r = self._responses[self.i]
        self.i += 1
        return r

    def estimate_cost(self, **kw):
        return Decimal("0.005")

    def count_tokens(self, **kw):
        return 120


def _run_tool_trace() -> str:
    @tool(
        name="my_tool",
        input_schema=_ToolIn,
        output_schema=_ToolOut,
        cost_per_call=Decimal("0.001"),
        deterministic=True,
    )
    def my_tool(args, ctx):
        return _ToolOut(answer="42")

    @behavior(name="planner", on=["goal.created"])
    def planner(event, graph, ctx):
        graph.add_object("doc", {"title": "d"})

    @llm_behavior(
        name="ex",
        on=["object.created"],
        where={"object.type": "doc"},
        description="Test.",
        output_schema=_Out,
        view={"around": "event.payload.object.id"},
        tools=[my_tool],
        deterministic=True,
    )
    def ex(event, graph, ctx, out):
        pass

    g = Graph(ids=IDGen(), clock=FrozenClock("2026-05-15T10:32:01Z"))
    rt = Runtime(g, llm_provider=_Provider())
    rt.run_goal("Tool demo")
    return "\n".join(rt.trace.lines()) + "\n"


def test_tool_trace_matches_snapshot():
    actual = _run_tool_trace()
    if os.environ.get("UPDATE_SNAPSHOTS"):
        os.makedirs(os.path.dirname(SNAPSHOT_PATH), exist_ok=True)
        with open(SNAPSHOT_PATH, "w") as f:
            f.write(actual)
    with open(SNAPSHOT_PATH) as f:
        expected = f.read()
    assert actual == expected, (
        "v0.7 tool/pattern trace drifted. If intentional, run with "
        "UPDATE_SNAPSHOTS=1 and update README's expected v0.7 trace block."
    )
