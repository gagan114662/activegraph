"""v0.6 killer demo: LLM behaviors on the active-graph substrate.

This file is the v0.6 contract. The API surface — `@llm_behavior`, the
`LLMProvider` interface, Pydantic-shaped structured outputs, the
`replay_llm_cache` knob, the 4-arg handler signature — is locked here
first; the runtime is built backward to make it run. Same discipline
as v0 (#17) and v0.5 (#20).

What this demo proves:

  1. A non-LLM `@behavior` (`planner`) creates three documents from the
     run's goal.
  2. A `@llm_behavior` (`claim_extractor`) reads each document via a
     scoped graph view, calls the LLM with a runtime-assembled prompt,
     and turns the parsed structured output into `claim` objects plus
     `supports` edges back to the source document. The developer writes
     the handler that consumes `llm_output`; the runtime writes the
     prompt, the events, and the provenance.
  3. A second non-LLM `@behavior` (`confidence_check`) reacts to the
     new claims and flags low-confidence ones.
  4. A `@relation_behavior` (`link_logger`) reacts to each new
     `supports` edge and patches the source document.
  5. We save the run to SQLite, then `fork` it at the goal event with
     `replay_llm_cache=True`. The fork rebuilds the same prompts and
     hits the cache populated from the parent's recorded
     `llm.responded` events — zero new API calls, but the same graph.
  6. Both traces print, including the new `[llm.requested]` /
     `[llm.responded]` lines. The fork's responded lines mark
     `cache_hit=true`.
  7. A `causal_chain` query on the first claim walks back through the
     LLM call's `llm.requested` event to the source document. That is
     the auditability story made concrete.

The demo ships its own tiny `_DemoScriptedProvider` so it runs without
an API key. The real-world flow is:

    from activegraph.llm import AnthropicProvider, RecordedLLMProvider
    provider = AnthropicProvider()              # reads ANTHROPIC_API_KEY
    # or for tests:
    provider = RecordedLLMProvider("tests/fixtures/llm")

Run it: `python examples/llm_claim_extraction.py`
"""

from __future__ import annotations

import json
import os
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

from activegraph import (
    Graph,
    Runtime,
    behavior,
    clear_registry,
    llm_behavior,
    relation_behavior,
)
from activegraph.llm import LLMMessage, LLMResponse


DB = "/tmp/activegraph_llm_claim_extraction.db"


# ---------- structured output schema ----------------------------------------


class Claim(BaseModel):
    """A single factual claim extracted from a document."""

    text: str = Field(description="The claim, in one short sentence.")
    confidence: float = Field(
        ge=0.0, le=1.0, description="How well the document supports the claim."
    )
    evidence_span: str = Field(
        description="The exact substring of the source document that supports the claim."
    )


class ClaimList(BaseModel):
    """The full set of claims extracted from one document."""

    claims: list[Claim]


# Pydantic's forward-reference resolution looks up `Claim` in the
# defining module's namespace. When this file is imported under a
# different module name (e.g. via importlib in the integration test),
# resolution fails unless we rebuild explicitly.
ClaimList.model_rebuild()


# ---------- the three source documents --------------------------------------


DOCUMENTS: list[tuple[str, str]] = [
    (
        "Q3 sales summary",
        "Q3 sales results show 14% YoY growth in the SMB segment, while "
        "enterprise contracts declined 3% over the same period.",
    ),
    (
        "Model card v4",
        "The v4 model achieves a 22% relative improvement on GSM8K over "
        "our previous best, with no regression on HumanEval.",
    ),
    (
        "Anecdotal retention chatter",
        "Some users have mentioned that retention might be slipping a bit "
        "in recent months, though we don't have hard numbers yet.",
    ),
]


# ---------- demo-only scripted LLM provider ---------------------------------


# Maps a unique substring of the user prompt to the canned model output.
# A real provider returns whatever the model actually said; this one
# just lets the demo run without a key.
_SCRIPTS: dict[str, list[dict[str, Any]]] = {
    "Q3 sales summary": [
        {
            "text": "SMB segment grew 14% YoY in Q3.",
            "confidence": 0.9,
            "evidence_span": "14% YoY growth in the SMB segment",
        },
        {
            "text": "Enterprise contracts declined 3% in Q3.",
            "confidence": 0.9,
            "evidence_span": "enterprise contracts declined 3%",
        },
    ],
    "Model card v4": [
        {
            "text": "v4 model improves GSM8K by 22% over the prior best.",
            "confidence": 0.85,
            "evidence_span": "22% relative improvement on GSM8K over our previous best",
        },
        {
            "text": "v4 model does not regress on HumanEval.",
            "confidence": 0.7,
            "evidence_span": "no regression on HumanEval",
        },
    ],
    "Anecdotal retention chatter": [
        {
            "text": "Retention may be declining in recent months.",
            "confidence": 0.4,  # low → confidence_check will flag it
            "evidence_span": "retention might be slipping a bit",
        },
    ],
}


class _DemoScriptedProvider:
    """Implements the `LLMProvider` protocol with canned responses.

    Demo-only: real production code uses `AnthropicProvider` or
    `RecordedLLMProvider`. We script by substring-matching the user
    message against `_SCRIPTS` keys; the real provider is unaware of
    such tricks.
    """

    def complete(
        self,
        *,
        system: str,
        messages: list[LLMMessage],
        model: str,
        max_tokens: int,
        temperature: float,
        top_p: float,
        output_schema: type | None,
        timeout_seconds: float,
        tools: list | None = None,
    ) -> LLMResponse:
        user_text = "\n".join(m.content for m in messages if m.role == "user")
        for needle, claims in _SCRIPTS.items():
            if needle in user_text:
                raw = json.dumps({"claims": claims}, sort_keys=True)
                parsed = (
                    output_schema.model_validate_json(raw) if output_schema else None
                )
                return LLMResponse(
                    raw_text=raw,
                    parsed=parsed,
                    input_tokens=max(1, len(user_text) // 4),
                    output_tokens=max(1, len(raw) // 4),
                    cost_usd=Decimal("0.001"),
                    latency_seconds=0.0,
                    model=model,
                    finish_reason="end_turn",
                )
        raise RuntimeError(
            f"_DemoScriptedProvider has no script for prompt; "
            f"first 200 chars of user text: {user_text[:200]!r}"
        )

    def estimate_cost(
        self, *, input_tokens: int, output_tokens: int, model: str
    ) -> Decimal:
        return Decimal("0.001")

    def count_tokens(
        self, *, system: str, messages: list[LLMMessage], model: str
    ) -> int:
        total = len(system) + sum(len(m.content) for m in messages)
        return max(1, total // 4)


# ---------- behaviors -------------------------------------------------------


def _register_behaviors() -> None:
    """Register both runs' behaviors. Behaviors are code, not state."""

    clear_registry()

    @behavior(name="planner", on=["goal.created"])
    def planner(event, graph, ctx):
        for title, body in DOCUMENTS:
            graph.add_object("document", {"title": title, "body": body})

    @llm_behavior(
        name="claim_extractor",
        on=["object.created"],
        where={"object.type": "document"},
        description=(
            "Extract verifiable factual claims from the document. "
            "Score each claim's confidence based on how directly the "
            "document supports it."
        ),
        model="claude-sonnet-4-5",
        output_schema=ClaimList,
        view={"around": "event.payload.object.id", "depth": 1},
        creates=["claim"],
        deterministic=True,
        budget={"max_llm_calls": 10},
    )
    def claim_extractor(event, graph, ctx, llm_output):
        doc_id = event.payload["object"]["id"]
        for claim in llm_output.claims:
            c = graph.add_object(
                "claim",
                {
                    "text": claim.text,
                    "confidence": claim.confidence,
                    "evidence_span": claim.evidence_span,
                    "status": "open",
                },
            )
            graph.add_relation(c.id, doc_id, "supports")

    @behavior(
        name="confidence_check",
        on=["object.created"],
        where={"object.type": "claim"},
    )
    def confidence_check(event, graph, ctx):
        c = event.payload["object"]
        if c["data"]["confidence"] < 0.5:
            graph.patch_object(c["id"], {"status": "needs_review"})

    @relation_behavior(
        name="link_logger", relation_type="supports", on=["relation.created"]
    )
    def link_logger(relation, event, graph, ctx):
        doc = graph.get_object(relation.target)
        if doc and not doc.data.get("has_claims"):
            graph.patch_object(relation.target, {"has_claims": True})


# ---------- the demo flow ---------------------------------------------------


def step_1_run_with_llm() -> Runtime:
    if os.path.exists(DB):
        os.remove(DB)
    _register_behaviors()

    provider = _DemoScriptedProvider()
    graph = Graph()
    rt = Runtime(
        graph,
        llm_provider=provider,
        persist_to=DB,
        budget={"max_llm_calls": 10, "max_cost_usd": "0.10"},
    )
    rt.run_goal("Survey Q3 market signals")
    rt.save_state()
    print(f"[step 1] run {rt.run_id}: "
          f"{len(rt.graph.all_objects())} objects, "
          f"{len(rt.graph.all_relations())} relations")
    return rt


def step_2_fork_with_cache(parent: Runtime) -> Runtime:
    """Fork at the goal event. With replay_llm_cache=True the fork
    rebuilds the same prompts but serves them from the parent's
    recorded llm.responded events — no new API calls."""

    goal_evt = next(e for e in parent.graph.events if e.type == "goal.created")
    _register_behaviors()  # behaviors are code, not state

    provider = _DemoScriptedProvider()  # same shape, would error if hit
    fork = parent.fork(
        at_event=goal_evt.id,
        label="cached-replay",
        replay_llm_cache=True,
        llm_provider=provider,
    )
    fork.run_until_idle()
    fork.save_state()
    print(f"[step 2] fork {fork.run_id}: "
          f"served {_count_cache_hits(fork)} LLM responses from cache")
    return fork


def step_3_print_traces(parent: Runtime, fork: Runtime) -> None:
    print("\n=== parent trace ===")
    parent.print_trace()
    print("\n=== fork trace (replay_llm_cache=True) ===")
    fork.print_trace()


def step_4_causal_chain(parent: Runtime) -> None:
    first_claim = next(
        o for o in parent.graph.all_objects() if o.type == "claim"
    )
    print(f"\n=== causal chain for {first_claim.id} ===")
    print(parent.trace.causal_chain(first_claim.id))


def _count_cache_hits(rt: Runtime) -> int:
    return sum(
        1
        for e in rt.graph.events
        if e.type == "llm.responded" and e.payload.get("cache_hit") is True
    )


if __name__ == "__main__":
    parent = step_1_run_with_llm()
    fork = step_2_fork_with_cache(parent)
    step_3_print_traces(parent, fork)
    step_4_causal_chain(parent)
