import pytest

from activegraph.core.graph import Graph


pytestmark = getattr(pytest.mark, "activegraph.core.graph.Graph.relations")


def test_activegraph_core_graph_graph_relations_filters_by_source_and_type() -> None:
    graph = Graph(run_id="run_t7m_010_source")
    source = graph.add_object("person", {"name": "source"})
    target = graph.add_object("person", {"name": "target"})
    other = graph.add_object("person", {"name": "other"})
    desired = graph.add_relation(source.id, target.id, "knows")
    graph.add_relation(source.id, other.id, "blocks")
    graph.add_relation(other.id, target.id, "knows")

    result = graph.relations(source=source.id, type="knows")

    assert result == [desired]


def test_activegraph_core_graph_graph_relations_filters_by_target() -> None:
    graph = Graph(run_id="run_t7m_010_target")
    source = graph.add_object("task", {"title": "source"})
    target = graph.add_object("task", {"title": "target"})
    unrelated = graph.add_object("task", {"title": "unrelated"})
    desired = graph.add_relation(source.id, target.id, "depends_on")
    graph.add_relation(source.id, unrelated.id, "depends_on")

    result = graph.relations(target=target.id)

    assert result == [desired]
