"""Integration test for examples/llm_claim_extraction.py.

The demo is the v0.6 contract — this test runs it end-to-end (in
a temp dir) and asserts the externally visible outcomes that lock
the public API surface.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile

import pytest


@pytest.fixture
def demo_module(monkeypatch):
    """Load examples/llm_claim_extraction.py as a module, with its DB
    redirected to a temp path."""

    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(here, "examples", "llm_claim_extraction.py")
    spec = importlib.util.spec_from_file_location("llm_claim_extraction_demo", path)
    mod = importlib.util.module_from_spec(spec)

    with tempfile.TemporaryDirectory() as td:
        db_path = os.path.join(td, "demo.db")
        # Patch DB before module body executes.
        spec.loader.exec_module(mod)
        monkeypatch.setattr(mod, "DB", db_path, raising=True)
        yield mod


def test_demo_step1_produces_documents_claims_and_supports_edges(demo_module):
    parent = demo_module.step_1_run_with_llm()
    objs = parent.graph.all_objects()
    assert sum(1 for o in objs if o.type == "document") == 3
    assert sum(1 for o in objs if o.type == "claim") == 5  # 2 + 2 + 1
    assert all(
        any(r.source == c.id for r in parent.graph.all_relations() if r.type == "supports")
        for c in objs
        if c.type == "claim"
    )


def test_demo_step1_flags_low_confidence_claim(demo_module):
    parent = demo_module.step_1_run_with_llm()
    flagged = [
        o
        for o in parent.graph.all_objects()
        if o.type == "claim" and o.data.get("status") == "needs_review"
    ]
    assert len(flagged) == 1
    assert "Retention" in flagged[0].data["text"]


def test_demo_step1_documents_get_has_claims_via_link_logger(demo_module):
    parent = demo_module.step_1_run_with_llm()
    docs = [o for o in parent.graph.all_objects() if o.type == "document"]
    assert all(d.data.get("has_claims") is True for d in docs)


def test_demo_fork_uses_cache_for_all_three_llm_calls(demo_module):
    parent = demo_module.step_1_run_with_llm()
    fork = demo_module.step_2_fork_with_cache(parent)
    cache_hits = sum(
        1
        for e in fork.graph.events
        if e.type == "llm.responded" and e.payload.get("cache_hit") is True
    )
    assert cache_hits == 3


def test_demo_causal_chain_crosses_llm_boundary(demo_module):
    parent = demo_module.step_1_run_with_llm()
    first_claim = next(
        o for o in parent.graph.all_objects() if o.type == "claim"
    )
    chain = parent.trace.causal_chain(first_claim.id)
    assert "llm.requested" in chain
    assert "llm.responded" in chain
    assert "goal.created" in chain
