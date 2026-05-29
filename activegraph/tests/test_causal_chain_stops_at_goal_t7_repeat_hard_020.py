"""T7 repeat-hard run 020 — docstring↔code drift regression test.

Target: ``activegraph.trace.causal.causal_chain``

The module docstring (activegraph/trace/causal.py, line 2) documents the
termination contract for the causal-chain walk:

    "Walk back from an object through caused_by links until we hit a
     goal.created (or an event with no parent)."

i.e. ``goal.created`` is the audit boundary — the chain renders lineage
back *to the goal that started the run* and stops there. Events ABOVE the
goal (runtime-internal lifecycle events such as ``runtime.started``) are
NOT part of an object's audit lineage and must not appear in the chain.

The bug: the walk loop only terminates on ``cursor.caused_by is None``
(no parent) or a cycle. It never checks for ``goal.created``. When a
``goal.created`` event itself has a ``caused_by`` parent (e.g. a
``runtime.started`` lifecycle event the runtime emitted first), the walk
leaks PAST the goal and renders the parent — contradicting the documented
"until we hit a goal.created" stop condition.

This test asserts the DOCUMENTED behavior and fails against the buggy code.
"""

from __future__ import annotations

from activegraph.core.clock import FrozenClock
from activegraph.core.event import Event
from activegraph.core.graph import Graph
from activegraph.core.ids import IDGen
from activegraph.trace.causal import causal_chain


def _graph_with_goal_under_a_parent() -> tuple[Graph, str]:
    """Build a graph where goal.created has a caused_by parent.

    Layout:
        runtime.started (evt_900, no parent)
          <- goal.created (evt_901, caused_by=evt_900)
              <- object.created (task#1, caused_by=evt_901)

    The documented contract says causal_chain(task#1) walks up to the
    goal.created and STOPS — runtime.started must not appear.
    """
    graph = Graph(ids=IDGen(), clock=FrozenClock())
    graph.emit(
        Event(
            id="evt_900",
            type="runtime.started",
            payload={},
            actor="runtime",
            timestamp="2026-05-15T10:32:01Z",
            caused_by=None,
        )
    )
    graph.emit(
        Event(
            id="evt_901",
            type="goal.created",
            payload={"goal": "diligence demo"},
            actor="user",
            timestamp="2026-05-15T10:32:01Z",
            caused_by="evt_900",
        )
    )
    obj = graph.add_object("task", {"title": "Investigate Acme"}, caused_by="evt_901")
    return graph, obj.id


def test_causal_chain_terminates_at_goal_created() -> None:
    """The chain must stop at goal.created, per the documented contract."""
    graph, object_id = _graph_with_goal_under_a_parent()

    chain = causal_chain(graph, object_id)

    # The goal IS part of the lineage — it must be shown.
    assert "goal.created" in chain
    # The parent of the goal is a runtime-internal lifecycle event ABOVE the
    # audit boundary; the documented "until we hit a goal.created" stop
    # condition means it must NOT leak into the chain.
    assert "runtime.started" not in chain


def test_causal_chain_still_stops_on_no_parent_when_no_goal() -> None:
    """Back-compat: the '(or an event with no parent)' branch still works.

    A chain with no goal.created at all must still terminate at the
    parentless root — the goal-stop must not regress the no-parent stop.
    """
    graph = Graph(ids=IDGen(), clock=FrozenClock())
    graph.emit(
        Event(
            id="evt_500",
            type="document.ingested",
            payload={},
            actor="system",
            timestamp="2026-05-15T10:32:01Z",
            caused_by=None,
        )
    )
    obj = graph.add_object("claim", {"text": "revenue grew"}, caused_by="evt_500")

    chain = causal_chain(graph, obj.id)

    # Root with no parent is rendered and the walk terminates there.
    assert "document.ingested" in chain
    assert "(cycle" not in chain
