import pytest

from activegraph.core.graph import Graph


pytestmark = getattr(pytest.mark, "activegraph.core.graph.Graph.get_object")


def test_activegraph_core_graph_graph_get_object_returns_existing_object() -> None:
    graph = Graph(run_id="run_t7m_014_existing")
    created = graph.add_object("task", {"title": "ship"})

    result = graph.get_object(created.id)

    assert result is created
    assert result is not None
    assert result.data == {"title": "ship"}


def test_activegraph_core_graph_graph_get_object_returns_none_for_unknown_id() -> None:
    graph = Graph(run_id="run_t7m_014_missing")
    graph.add_object("task", {"title": "present"})

    assert graph.get_object("obj_missing") is None
