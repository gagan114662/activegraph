import pytest

from activegraph.core.graph import Graph


pytestmark = getattr(pytest.mark, "activegraph.core.graph.Graph.all_relations")


def test_activegraph_core_graph_graph_all_relations_returns_every_relation() -> None:
    graph = Graph(run_id="run_t7m_017_all")
    a = graph.add_object("person", {"name": "a"})
    b = graph.add_object("person", {"name": "b"})
    c = graph.add_object("person", {"name": "c"})
    r1 = graph.add_relation(a.id, b.id, "knows")
    r2 = graph.add_relation(b.id, c.id, "blocks")
    r3 = graph.add_relation(a.id, c.id, "knows")

    result = graph.all_relations()

    assert sorted(r.id for r in result) == sorted([r1.id, r2.id, r3.id])
    assert {r.type for r in result} == {"knows", "blocks"}


def test_activegraph_core_graph_graph_all_relations_empty_when_no_relations() -> None:
    graph = Graph(run_id="run_t7m_017_empty")
    graph.add_object("task", {"title": "lone-object"})

    result = graph.all_relations()

    assert result == []


def test_activegraph_core_graph_graph_all_relations_excludes_removed() -> None:
    graph = Graph(run_id="run_t7m_017_removed")
    src = graph.add_object("doc", {"title": "src"})
    dst = graph.add_object("doc", {"title": "dst"})
    kept = graph.add_relation(src.id, dst.id, "links_to")
    doomed = graph.add_relation(dst.id, src.id, "links_to")

    graph.remove_relation(doomed.id)
    result = graph.all_relations()

    assert [r.id for r in result] == [kept.id]
