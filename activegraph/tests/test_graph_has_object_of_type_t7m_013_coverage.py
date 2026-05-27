import pytest

from activegraph.core.graph import Graph


pytestmark = getattr(pytest.mark, "activegraph.core.graph.Graph.has_object_of_type")


def test_activegraph_core_graph_graph_has_object_of_type_returns_true_for_existing_type() -> None:
    graph = Graph(run_id="run_t7m_013_existing")
    graph.add_object("task", {"title": "ship"})
    graph.add_object("note", {"title": "memo"})

    assert graph.has_object_of_type("task") is True


def test_activegraph_core_graph_graph_has_object_of_type_returns_false_for_missing_type() -> None:
    graph = Graph(run_id="run_t7m_013_missing")
    graph.add_object("note", {"title": "memo"})

    assert graph.has_object_of_type("task") is False
