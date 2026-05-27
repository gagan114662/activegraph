import pytest

from activegraph.core.graph import Graph


pytestmark = getattr(pytest.mark, "activegraph.core.graph.Graph.events")


def test_activegraph_core_graph_graph_events_returns_emitted_events_in_order() -> None:
    graph = Graph(run_id="run_t7m_011_order")

    created = graph.add_object("task", {"title": "ship"})
    relation = graph.add_relation(created.id, created.id, "self")

    events = graph.events

    assert [event.type for event in events] == ["object.created", "relation.created"]
    assert events[0].payload["id"] == created.id
    assert events[1].payload["id"] == relation.id


def test_activegraph_core_graph_graph_events_returns_a_copy() -> None:
    graph = Graph(run_id="run_t7m_011_copy")
    graph.add_object("task", {"title": "copy"})

    first_snapshot = graph.events
    first_snapshot.clear()

    assert len(first_snapshot) == 0
    assert len(graph.events) == 1
