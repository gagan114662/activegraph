import pytest

from activegraph.core.graph import Graph


pytestmark = getattr(pytest.mark, "activegraph.core.graph.Graph.objects")


def test_activegraph_core_graph_graph_objects_filters_by_type() -> None:
    graph = Graph(run_id="run_t7m_012_type")
    note = graph.add_object("note", {"title": "ship"})
    graph.add_object("task", {"title": "review"})

    result = graph.objects(type="note")

    assert result == [note]


def test_activegraph_core_graph_graph_objects_filters_by_top_level_where() -> None:
    graph = Graph(run_id="run_t7m_012_where")
    active = graph.add_object("task", {"state": "active", "priority": 2})
    graph.add_object("task", {"state": "archived", "priority": 5})

    result = graph.objects(where={"state": "active", "priority": {">=": 2}})

    assert result == [active]
