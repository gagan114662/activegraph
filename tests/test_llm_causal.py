"""Causal chain crosses the LLM boundary (CONTRACT v0.6 #15)."""

from __future__ import annotations

from activegraph import Graph, Runtime, behavior, llm_behavior

from tests._llm_helpers import Claim, ClaimList, ScriptedProvider


def test_causal_chain_walks_through_llm_request_event():
    @behavior(name="seed", on=["goal.created"])
    def seed(event, graph, ctx):
        graph.add_object("document", {"title": "T", "body": "B"})

    @llm_behavior(
        name="extractor",
        on=["object.created"],
        where={"object.type": "document"},
        output_schema=ClaimList,
        view={"around": "event.payload.object.id", "depth": 1},
    )
    def extractor(event, graph, ctx, llm_output):
        for c in llm_output.claims:
            graph.add_object("claim", {"text": c.text, "confidence": c.confidence})

    provider = ScriptedProvider(
        respond_fn=lambda m, s: ClaimList(
            claims=[Claim(text="market is growing", confidence=0.9)]
        )
    )
    g = Graph()
    rt = Runtime(g, llm_provider=provider)
    rt.run_goal("Audit the doc")

    claim = next(o for o in g.all_objects() if o.type == "claim")
    chain = rt.trace.causal_chain(claim.id)
    lines = chain.splitlines()
    # First line names the claim object.
    assert claim.id in lines[0]
    # Somewhere in the chain we see llm.requested + llm.responded + the
    # triggering object.created chain back to the goal.
    full = "\n".join(lines)
    assert "llm.requested" in full
    assert "llm.responded" in full
    assert "model=claude-sonnet-4-5" in full
    assert "goal.created" in full


def test_causal_chain_for_non_llm_object_unchanged():
    """Backward compat: when an object wasn't created inside an
    @llm_behavior, the chain renders exactly as v0/v0.5."""

    @behavior(name="planner", on=["goal.created"])
    def planner(event, graph, ctx):
        graph.add_object("task", {"title": "Work"})

    g = Graph()
    Runtime(g).run_goal("g")
    chain = g.events  # just confirms run executed
    assert any(o.type == "task" for o in g.all_objects())

    from activegraph.trace.causal import causal_chain

    out = causal_chain(g, "task#1")
    assert "llm.requested" not in out
    assert "goal.created" in out
