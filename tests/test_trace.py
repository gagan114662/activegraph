"""Trace export (JSONL) and causal-chain audit. Both documented in README."""

import json
import os

from activegraph import FrozenClock, Graph, IDGen, Runtime, behavior


def test_export_trace_writes_jsonl(tmp_path):
    @behavior(name="p", on=["goal.created"])
    def p(event, graph, ctx):
        graph.add_object("task", {"title": "x"})

    g = Graph(ids=IDGen(), clock=FrozenClock())
    r = Runtime(g)
    r.run_goal("hi")
    out = tmp_path / "run.jsonl"
    r.export_trace(str(out))
    lines = out.read_text().strip().splitlines()
    assert len(lines) == len(g.events)
    # Each line is valid JSON with the standard event keys.
    first = json.loads(lines[0])
    assert {"id", "type", "payload", "actor", "timestamp"} <= set(first.keys())


def test_causal_chain_walks_back_to_goal():
    @behavior(name="p", on=["goal.created"])
    def p(event, graph, ctx):
        graph.add_object("artifact", {"title": "memo"})

    g = Graph(ids=IDGen(), clock=FrozenClock())
    r = Runtime(g)
    r.run_goal("evaluate")

    artifact = next(o for o in g.all_objects() if o.type == "artifact")
    chain = r.trace.causal_chain(artifact.id)
    assert artifact.id in chain
    # Should mention the originating goal event somewhere up the chain.
    assert "goal.created" in chain
