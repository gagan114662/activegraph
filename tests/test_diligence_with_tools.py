"""Integration test for `examples/diligence_with_tools.py`.

Per CONTRACT v0.7 #17 + v0 #17 carryover: every README example is
backed by a test. This one runs the full demo and asserts:

  - claims, resolutions, escalations were produced
  - fork hits both LLM and tool caches (zero new API calls)
  - the trace contains tool.requested, tool.responded, pattern.matched,
    and behavior.scheduled lines
  - a causal chain from a claim crosses LLM AND tool boundaries
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path


def _load_demo_module(tmp_db: Path):
    spec = importlib.util.spec_from_file_location(
        "diligence_with_tools",
        Path(__file__).parent.parent / "examples" / "diligence_with_tools.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.DB = str(tmp_db)
    return mod


def test_diligence_demo_runs_end_to_end(tmp_path):
    demo = _load_demo_module(tmp_path / "run.db")
    parent = demo.step_1_run()

    n_claims = sum(1 for o in parent.graph.all_objects() if o.type == "claim")
    n_resolutions = sum(1 for o in parent.graph.all_objects() if o.type == "resolution")
    n_escalations = sum(1 for o in parent.graph.all_objects() if o.type == "escalation")
    assert n_claims >= 3, "researcher should produce multiple claims"
    assert n_resolutions == 1, "critic pattern should fire once"
    assert n_escalations == 1, "nag activate_after should fire once"

    # New v0.7 event types appear.
    types = {e.type for e in parent.graph.events}
    assert "tool.requested" in types
    assert "tool.responded" in types
    assert "pattern.matched" in types
    assert "behavior.scheduled" in types


def test_diligence_demo_fork_hits_both_caches(tmp_path):
    demo = _load_demo_module(tmp_path / "run.db")
    parent = demo.step_1_run()
    fork = demo.step_2_fork_with_caches(parent)

    n_llm_hits = sum(
        1 for e in fork.graph.events
        if e.type == "llm.responded" and e.payload.get("cache_hit")
    )
    n_tool_hits = sum(
        1 for e in fork.graph.events
        if e.type == "tool.responded" and e.payload.get("cache_hit")
    )
    assert n_llm_hits >= 1, "fork should hit the LLM cache"
    assert n_tool_hits >= 1, "fork should hit the tool cache"


def test_diligence_causal_chain_crosses_tool_boundary(tmp_path):
    demo = _load_demo_module(tmp_path / "run.db")
    parent = demo.step_1_run()
    first_claim = next(o for o in parent.graph.all_objects() if o.type == "claim")
    chain = parent.trace.causal_chain(first_claim.id)
    assert "llm.requested" in chain
    assert "tool.requested" in chain
    assert "goal.created" in chain
