import pytest

from activegraph.core.graph import Graph


pytestmark = getattr(pytest.mark, "activegraph.core.graph.Graph.neighborhood")


def test_activegraph_core_graph_graph_neighborhood_returns_depth_one_slice() -> None:
    graph = Graph(run_id="run_t7m_009_depth")
    center = graph.add_object("person", {"name": "center"})
    neighbor = graph.add_object("person", {"name": "neighbor"})
    distant = graph.add_object("person", {"name": "distant"})
    direct = graph.add_relation(center.id, neighbor.id, "knows")
    graph.add_relation(neighbor.id, distant.id, "knows")

    objects, relations = graph.neighborhood(center.id, depth=1)

    assert {obj.id for obj in objects} == {center.id, neighbor.id}
    assert [rel.id for rel in relations] == [direct.id]


def test_activegraph_core_graph_graph_neighborhood_returns_empty_for_unknown_object() -> None:
    graph = Graph(run_id="run_t7m_009_missing")
    graph.add_object("person", {"name": "present"})

    objects, relations = graph.neighborhood("obj_missing", depth=2)

    assert objects == []
    assert relations == []
