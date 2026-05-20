"""Killer demo for frame `v0-promote-runtime-diff`.

Spec-first: this file is the executable definition of what "diff.py is
mypy --strict clean" means in user terms. It is written BEFORE the typing
promotion lands on `activegraph/runtime/diff.py`. If the promotion is
real, BOTH of these succeed:

    python examples/v0_promote_runtime_diff.py
    mypy --strict examples/v0_promote_runtime_diff.py

Success criteria (the demo enforces these at runtime via `assert`):
  Scenario A — two graphs that share a setup prefix and then diverge:
    - 1 shared event (the first object.created on both sides)
    - >= 1 parent-only and >= 1 fork-only event
    - 1 divergent object (the task that got a different title in fork)
    - 1 divergent relation (the depends_on edge that exists only in parent)
    - Diff.is_identical is False
  Scenario B — two graphs with identical setup:
    - 0 divergent objects, 0 divergent relations
    - All events on both sides are shared
    - Diff.is_identical is True

The runtime assertions and the (mypy-only) `reveal_type` block at the
bottom together make any future drift on `runtime/diff.py`'s public
surface trip either the test runner or the type checker.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from activegraph.core.clock import FrozenClock
from activegraph.core.event import Event
from activegraph.core.graph import Graph, Object, Relation
from activegraph.core.ids import IDGen
from activegraph.runtime.diff import (
    Diff,
    DivergentObject,
    DivergentRelation,
    compute_diff,
)

PARENT_RUN_ID: str = "demo-parent"
FORK_RUN_ID: str = "demo-fork"


def _fresh_graph(run_id: str) -> Graph:
    """A graph with deterministic IDs + clock so payloads compare equal."""
    return Graph(ids=IDGen(), clock=FrozenClock(), run_id=run_id)


def _build_parent() -> Graph:
    g: Graph = _fresh_graph(PARENT_RUN_ID)
    research: Object = g.add_object(
        "task", {"title": "Research market", "status": "open"}
    )
    memo: Object = g.add_object(
        "task", {"title": "Draft memo", "status": "blocked"}
    )
    edge: Relation = g.add_relation(research.id, memo.id, "depends_on")
    assert edge.source == research.id  # narrows for the reader; mypy already knows
    g.add_object(
        "claim",
        {"text": "Market appears early but growing.", "confidence": 0.7},
    )
    return g


def _build_fork_shared_prefix() -> Graph:
    """Same first object as parent (shared prefix), then diverge."""
    g: Graph = _fresh_graph(PARENT_RUN_ID)  # same run_id => provenance matches
    g.add_object("task", {"title": "Research market", "status": "open"})
    # diverge: different title, no depends_on edge, different claim
    g.add_object("task", {"title": "Counter-memo", "status": "open"})
    g.add_object(
        "claim",
        {"text": "Counter: market is saturated.", "confidence": 0.6},
    )
    return g


def _build_identical_pair() -> tuple[Graph, Graph]:
    def populate(run_id: str) -> Graph:
        g = _fresh_graph(run_id)
        a = g.add_object("task", {"title": "Same", "status": "open"})
        b = g.add_object("task", {"title": "Same2", "status": "open"})
        g.add_relation(a.id, b.id, "depends_on")
        return g

    return populate(PARENT_RUN_ID), populate(PARENT_RUN_ID)


def _print_diff(label: str, diff: Diff) -> None:
    print(f"\n=== {label} ===")
    print(f"  parent_run_id:        {diff.parent_run_id}")
    print(f"  fork_run_id:          {diff.fork_run_id}")
    print(f"  shared events:        {len(diff.shared_events)}")
    print(f"  parent-only events:   {len(diff.parent_only_events)}")
    print(f"  fork-only events:     {len(diff.fork_only_events)}")
    print(f"  divergent objects:    {len(diff.divergent_objects)}")
    for obj in diff.divergent_objects:
        # `obj` is statically a DivergentObject; .summary() returns str
        print(f"    - {obj.summary()}")
    print(f"  divergent relations:  {len(diff.divergent_relations)}")
    for rel in diff.divergent_relations:
        print(f"    - {rel.summary()}")
    print(f"  is_identical:         {diff.is_identical}")


def scenario_a_diverging() -> Diff:
    parent: Graph = _build_parent()
    fork: Graph = _build_fork_shared_prefix()
    diff: Diff = compute_diff(parent, fork, PARENT_RUN_ID, FORK_RUN_ID)

    _print_diff("Scenario A: shared prefix then divergence", diff)

    # Behavioural assertions — these define what "diff works" means.
    assert isinstance(diff, Diff)
    assert diff.parent_run_id == PARENT_RUN_ID
    assert diff.fork_run_id == FORK_RUN_ID
    assert len(diff.shared_events) == 1, diff.shared_events
    assert len(diff.parent_only_events) >= 1
    assert len(diff.fork_only_events) >= 1
    for e in diff.shared_events:
        assert isinstance(e, Event)
    assert len(diff.divergent_objects) >= 1
    assert all(isinstance(o, DivergentObject) for o in diff.divergent_objects)
    assert len(diff.divergent_relations) == 1
    only_rel: DivergentRelation = diff.divergent_relations[0]
    assert only_rel.in_parent is not None and only_rel.in_fork is None
    assert "only in parent" in only_rel.summary()
    assert diff.is_identical is False
    return diff


def scenario_b_identical() -> Diff:
    parent, fork = _build_identical_pair()
    diff: Diff = compute_diff(parent, fork, PARENT_RUN_ID, PARENT_RUN_ID)

    _print_diff("Scenario B: identical pair", diff)

    assert diff.divergent_objects == []
    assert diff.divergent_relations == []
    assert diff.parent_only_events == []
    assert diff.fork_only_events == []
    assert diff.is_identical is True
    return diff


def main() -> None:
    scenario_a_diverging()
    scenario_b_identical()
    print("\nOK — runtime/diff.py public surface behaves as specified.")


if TYPE_CHECKING:
    # Lightweight contract check for the type-checker. If `compute_diff`
    # ever loses its strict signature, this block fails under mypy --strict
    # without affecting runtime behaviour.
    from typing import assert_type

    _parent: Graph
    _fork: Graph
    _d: Diff = compute_diff(_parent, _fork, "p", "f")
    assert_type(_d.shared_events, list[Event])
    assert_type(_d.parent_only_events, list[Event])
    assert_type(_d.fork_only_events, list[Event])
    assert_type(_d.divergent_objects, list[DivergentObject])
    assert_type(_d.divergent_relations, list[DivergentRelation])
    assert_type(_d.is_identical, bool)
    _do: DivergentObject = _d.divergent_objects[0] if _d.divergent_objects else DivergentObject(id="", in_parent=None, in_fork=None)
    assert_type(_do.summary(), str)
    _dr: DivergentRelation = _d.divergent_relations[0] if _d.divergent_relations else DivergentRelation(id="", in_parent=None, in_fork=None)
    assert_type(_dr.summary(), str)


if __name__ == "__main__":
    main()
