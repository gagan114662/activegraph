import pytest

from activegraph.core.graph import Graph
from activegraph.core.graph import Relation


pytestmark = getattr(pytest.mark, "activegraph.core.graph.Graph.get_relation")


def test_activegraph_core_graph_graph_get_relation_returns_existing_relation() -> None:
    graph = Graph(run_id="run_t7m_019_existing")
    source = graph.add_object("person", {"name": "source"})
    target = graph.add_object("person", {"name": "target"})

    relation = graph.add_relation(source.id, target.id, "knows", {"since": 2026})
    result = graph.get_relation(relation.id)

    assert isinstance(result, Relation)
    assert result is relation
    assert result.source == source.id
    assert result.target == target.id
    assert result.type == "knows"
    assert result.data == {"since": 2026}


def test_activegraph_core_graph_graph_get_relation_returns_none_for_unknown_id() -> None:
    graph = Graph(run_id="run_t7m_019_missing")
    source = graph.add_object("task", {"title": "source"})
    target = graph.add_object("task", {"title": "target"})
    graph.add_relation(source.id, target.id, "depends_on")

    assert graph.get_relation("rel_missing") is None
