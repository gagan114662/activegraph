"""Snapshot test for the v0.6 LLM trace. CONTRACT v0.6 #14 — the
`[llm.requested]` / `[llm.responded]` lines are part of the public
trace format. This is the canary for any drift.

If you change the format on purpose, update the snapshot in the same
commit and update the README's expected LLM trace block.
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
)
from activegraph.llm import LLMMessage, LLMResponse


SNAPSHOT_PATH = os.path.join(
    os.path.dirname(__file__), "snapshots", "llm_trace.txt"
)


class Claim(BaseModel):
    text: str
    confidence: float


class ClaimList(BaseModel):
    claims: list[Claim]


ClaimList.model_rebuild()


class _DeterministicProvider:
    """Returns a fixed response with stable token counts, cost, and
    latency — required for trace stability across runs."""

    def complete(self, *, system, messages, model, max_tokens, temperature,
                 top_p, output_schema, timeout_seconds):
        parsed = ClaimList(claims=[Claim(text="Sample claim.", confidence=0.9)])
        return LLMResponse(
            raw_text=parsed.model_dump_json(),
            parsed=parsed,
            input_tokens=120,
            output_tokens=24,
            cost_usd=Decimal("0.0012"),
            latency_seconds=0.5,
            model=model,
            finish_reason="end_turn",
        )

    def estimate_cost(self, *, input_tokens, output_tokens, model):
        return Decimal("0.005")

    def count_tokens(self, *, system, messages, model):
        return 120


def _run_llm_trace() -> str:
    @behavior(name="planner", on=["goal.created"])
    def planner(event, graph, ctx):
        graph.add_object("document", {"title": "Doc", "body": "body"})

    @llm_behavior(
        name="extractor",
        on=["object.created"],
        where={"object.type": "document"},
        description="Extract claims.",
        output_schema=ClaimList,
        view={"around": "event.payload.object.id", "depth": 1},
        creates=["claim"],
        deterministic=True,
    )
    def extractor(event, graph, ctx, llm_output):
        for c in llm_output.claims:
            graph.add_object(
                "claim", {"text": c.text, "confidence": c.confidence}
            )

    g = Graph(ids=IDGen(), clock=FrozenClock("2026-05-15T10:32:01Z"))
    rt = Runtime(
        g,
        llm_provider=_DeterministicProvider(),
        budget={"max_cost_usd": "1.00", "max_events": 200},
        seed=0,
    )
    rt.run_goal("Audit Q3")
    return "\n".join(rt.trace.lines()) + "\n"


def test_llm_trace_matches_snapshot():
    actual = _run_llm_trace()
    if os.environ.get("UPDATE_SNAPSHOTS"):
        os.makedirs(os.path.dirname(SNAPSHOT_PATH), exist_ok=True)
        with open(SNAPSHOT_PATH, "w") as f:
            f.write(actual)
    with open(SNAPSHOT_PATH) as f:
        expected = f.read()
    assert actual == expected, (
        "LLM trace drifted. If intentional, run with UPDATE_SNAPSHOTS=1 "
        "and update README's expected LLM trace block in the same commit."
    )
