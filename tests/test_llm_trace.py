"""Trace format for llm.* events (CONTRACT v0.6 #14).

Snapshot-tested layout: `[llm.requested]` and `[llm.responded]` follow
the tag padding rule and include the event id, behavior name, model,
estimated/actual token counts, cost, latency, and the cache_hit flag
when applicable.
"""

from __future__ import annotations

import os
import tempfile

from activegraph import Graph, Runtime, behavior, clear_registry, llm_behavior

from tests._llm_helpers import Claim, ClaimList, ScriptedProvider


def _register():
    @behavior(name="seed", on=["goal.created"])
    def seed(event, graph, ctx):
        graph.add_object("document", {"title": "T", "body": "B"})

    @llm_behavior(
        name="extractor",
        on=["object.created"],
        where={"object.type": "document"},
        output_schema=ClaimList,
        view={"around": "event.payload.object.id", "depth": 1},
        deterministic=True,
    )
    def extractor(event, graph, ctx, llm_output):
        pass


def _scripted():
    return ScriptedProvider(
        respond_fn=lambda m, s: ClaimList(claims=[Claim(text="x", confidence=0.9)])
    )


def test_trace_includes_llm_lines_with_tokens_and_cost():
    clear_registry()
    _register()
    g = Graph()
    rt = Runtime(
        g, llm_provider=_scripted(), budget={"max_cost_usd": "1.00"}
    )
    rt.run_goal("g")
    lines = rt.trace.lines()

    req_line = next(line for line in lines if line.startswith("[llm.requested]"))
    resp_line = next(line for line in lines if line.startswith("[llm.responded]"))

    # llm.requested format: tag + evt_id + behavior + model + tokens_in~ + budget
    assert "model=claude-sonnet-4-5" in req_line
    assert "tokens_in~" in req_line  # ~ for estimate
    assert "budget_remaining=$" in req_line

    # llm.responded format: tag + evt_id + behavior + tokens + cost + latency
    assert "tokens_in=" in resp_line  # no ~ for actual
    assert "tokens_out=" in resp_line
    assert "cost=$" in resp_line
    assert "latency=" in resp_line


def test_trace_no_tokens_in_estimate_when_no_cost_budget():
    """When max_cost_usd isn't set, we don't pre-count tokens, so the
    estimate is absent from the trace line."""

    clear_registry()
    _register()
    g = Graph()
    rt = Runtime(g, llm_provider=_scripted())  # no max_cost_usd
    rt.run_goal("g")
    req_line = next(
        line for line in rt.trace.lines() if line.startswith("[llm.requested]")
    )
    assert "tokens_in~" not in req_line
    assert "budget_remaining=" not in req_line


def test_trace_marks_cache_hit_lines():
    clear_registry()
    _register()
    db = tempfile.mktemp(suffix=".db")
    try:
        g = Graph()
        rt = Runtime(g, llm_provider=_scripted(), persist_to=db)
        rt.run_goal("g")
        goal = next(e for e in g.events if e.type == "goal.created")

        clear_registry()
        _register()
        fork = rt.fork(
            at_event=goal.id,
            label="cached",
            replay_llm_cache=True,
            llm_provider=_scripted(),
        )
        fork.run_until_idle()

        fork_lines = fork.trace.lines()
        req = next(l for l in fork_lines if l.startswith("[llm.requested]"))
        resp = next(l for l in fork_lines if l.startswith("[llm.responded]"))
        assert "cache_hit=true" in req
        assert "cache_hit=true" in resp
        # Cache-hit responded does NOT show cost/latency (they're cached values).
        assert "cost=$" not in resp
        assert "latency=" not in resp
    finally:
        if os.path.exists(db):
            os.remove(db)


def test_trace_tag_padding_unchanged_v0_v05_lines():
    """v0 / v0.5 tag padding stays exactly 26 chars — backward compat."""

    clear_registry()

    @behavior(name="planner", on=["goal.created"])
    def planner(event, graph, ctx):
        graph.add_object("task", {"title": "x"})

    g = Graph()
    Runtime(g).run_goal("g")
    for line in g.events:
        pass
    rendered = "\n".join(
        line
        for line in __import__("activegraph.trace.printer", fromlist=["Trace"]).Trace(g).lines()
    )
    # Same constant TAG_COL from printer.
    from activegraph.trace.printer import TAG_COL

    for raw in rendered.splitlines():
        if raw.startswith("["):
            bracket_end = raw.index("]")
            tag = raw[: bracket_end + 1]
            # If the tag is short, it's padded to TAG_COL chars.
            if len(tag) < TAG_COL:
                assert raw[:TAG_COL].endswith(" "), (
                    f"padding broken on line: {raw!r}"
                )
