"""T7 medium run 016 coverage for ``activegraph.core.graph.Graph.remove_relation``.

The relation-removal mutator had no test that targeted it directly (it was only
used incidentally as a helper inside the ``all_relations`` coverage test). These
tests exercise distinct configurations of the public API:

- happy path: an existing relation is removed from graph state
- event semantics: removal emits exactly one ``relation.removed`` event
- boundary/no-op: removing an unknown id is silent (no raise, no event)
- idempotency: removing the same relation twice only emits one event
- provenance: the emitted event carries the supplied actor/caused_by/frame_id

Real ``Graph`` fixtures are used throughout; the API under test is not mocked.
"""

import pytest

from activegraph.core.graph import Graph


pytestmark = getattr(pytest.mark, "activegraph.core.graph.Graph.remove_relation")


def _graph_with_relation(run_id: str):
    """Build a real two-object graph joined by one relation."""
    graph = Graph(run_id=run_id)
    src = graph.add_object("person", {"name": "src"})
    dst = graph.add_object("person", {"name": "dst"})
    rel = graph.add_relation(src.id, dst.id, "knows")
    return graph, rel


def test_activegraph_core_graph_graph_remove_relation_drops_existing_relation() -> None:
    graph, rel = _graph_with_relation("run_t7m_016_happy")

    assert graph.get_relation(rel.id) is not None  # present before removal

    result = graph.remove_relation(rel.id)

    assert result is None
    assert graph.get_relation(rel.id) is None
    assert [r.id for r in graph.all_relations()] == []


def test_activegraph_core_graph_graph_remove_relation_emits_single_removed_event() -> None:
    graph, rel = _graph_with_relation("run_t7m_016_event")

    before = sum(1 for e in graph.events if e.type == "relation.removed")
    graph.remove_relation(rel.id)
    removed = [e for e in graph.events if e.type == "relation.removed"]

    assert before == 0
    assert len(removed) == 1
    assert removed[0].payload["id"] == rel.id


def test_activegraph_core_graph_graph_remove_relation_unknown_id_is_silent_noop() -> None:
    graph, rel = _graph_with_relation("run_t7m_016_unknown")

    events_before = len(graph.events)
    relations_before = {r.id for r in graph.all_relations()}

    # Unknown id must not raise and must not mutate state or emit an event.
    result = graph.remove_relation("rel_does_not_exist")

    assert result is None
    assert len(graph.events) == events_before
    assert {r.id for r in graph.all_relations()} == relations_before
    assert rel.id in relations_before


def test_activegraph_core_graph_graph_remove_relation_is_idempotent() -> None:
    graph, rel = _graph_with_relation("run_t7m_016_idempotent")

    graph.remove_relation(rel.id)
    # Second removal of the now-absent relation is a no-op: no new event.
    graph.remove_relation(rel.id)

    removed = [e for e in graph.events if e.type == "relation.removed"]
    assert len(removed) == 1
    assert graph.get_relation(rel.id) is None


def test_activegraph_core_graph_graph_remove_relation_records_provenance_fields() -> None:
    graph, rel = _graph_with_relation("run_t7m_016_provenance")

    graph.remove_relation(
        rel.id,
        actor="maya",
        caused_by="cause_event_42",
        frame_id="frame_016",
    )

    removed = [e for e in graph.events if e.type == "relation.removed"]
    assert len(removed) == 1
    event = removed[0]
    assert event.actor == "maya"
    assert event.caused_by == "cause_event_42"
    assert event.frame_id == "frame_016"
