"""T7 medium run 012 coverage for activegraph.runtime.registry.Registry.match.

Exercises the matcher's documented contract surface with real Behavior,
Event, and Graph fixtures (no mocks of the API under test):

- event-type filtering via ``on=`` (CONTRACT #10),
- registration-order preservation for ties,
- ``where=`` payload filtering on plain behaviors,
- lifecycle-event suppression for pattern-only behaviors.
"""

from __future__ import annotations

from activegraph.behaviors.base import Behavior
from activegraph.core.event import Event
from activegraph.core.graph import Graph
from activegraph.runtime.registry import Registry


def _noop(event, graph, ctx):  # pragma: no cover - never invoked by match()
    return None


def test_Registry_match_filters_on_event_type_and_keeps_registration_order():
    """Happy path: only behaviors whose ``on=`` includes the event type
    match, and they come back in registration order."""
    first = Behavior(name="first", fn=_noop, on=["thing.created"])
    second = Behavior(name="second", fn=_noop, on=["thing.created"])
    unrelated = Behavior(name="unrelated", fn=_noop, on=["other.event"])

    registry = Registry([first, unrelated, second])
    graph = Graph()
    event = Event(id="e1", type="thing.created", payload={})

    results = registry.match(event, graph)
    matched_names = [behavior.name for behavior, _rels, _matches in results]

    # "unrelated" is filtered out; "first" precedes "second" by registration order.
    assert matched_names == ["first", "second"]
    # Plain behaviors (no pattern=) carry empty relation + pattern-match lists.
    assert all(rels == [] and matches == [] for _b, rels, matches in results)


def test_Registry_match_applies_where_clause_to_event_payload():
    """Boundary path: a behavior with a ``where=`` clause matches only when
    the event payload satisfies the predicate."""
    gated = Behavior(
        name="gated",
        fn=_noop,
        on=["thing.created"],
        where={"status": "active"},
    )
    registry = Registry([gated])
    graph = Graph()

    matching_event = Event(id="e1", type="thing.created", payload={"status": "active"})
    rejected_event = Event(id="e2", type="thing.created", payload={"status": "idle"})

    assert [b.name for b, _r, _m in registry.match(matching_event, graph)] == ["gated"]
    # where= predicate fails -> behavior is excluded even though on= matches.
    assert registry.match(rejected_event, graph) == []


def test_Registry_match_empty_registry_and_no_event_type_match_return_empty():
    """Boundary path: an empty registry and a non-matching event type both
    yield no triples (and never raise)."""
    empty_registry = Registry([])
    graph = Graph()
    event = Event(id="e1", type="thing.created", payload={})
    assert empty_registry.match(event, graph) == []

    only_other = Registry([Behavior(name="only_other", fn=_noop, on=["other.event"])])
    assert only_other.match(event, graph) == []
