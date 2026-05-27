import pytest

from activegraph.core.graph import Graph, Object


pytestmark = getattr(pytest.mark, "activegraph.core.graph.Graph.all_objects")


def test_activegraph_core_graph_graph_all_objects_returns_empty_list_on_fresh_graph() -> None:
    graph = Graph(run_id="run_t7m_015_empty")

    result = graph.all_objects()

    assert result == []
    assert isinstance(result, list)


def test_activegraph_core_graph_graph_all_objects_returns_every_added_object_across_types() -> None:
    graph = Graph(run_id="run_t7m_015_mixed")
    task = graph.add_object("task", {"title": "ship"})
    note = graph.add_object("note", {"body": "remember"})
    other_task = graph.add_object("task", {"title": "review"})

    result = graph.all_objects()

    assert len(result) == 3
    ids = {o.id for o in result}
    assert ids == {task.id, note.id, other_task.id}
    assert all(isinstance(o, Object) for o in result)


def test_activegraph_core_graph_graph_all_objects_reflects_removal_and_is_isolated_snapshot() -> None:
    graph = Graph(run_id="run_t7m_015_remove")
    keep = graph.add_object("task", {"title": "keep"})
    drop = graph.add_object("task", {"title": "drop"})

    snapshot = graph.all_objects()
    assert {o.id for o in snapshot} == {keep.id, drop.id}

    # Mutating the returned list must not affect the graph.
    snapshot.clear()
    assert {o.id for o in graph.all_objects()} == {keep.id, drop.id}

    graph.remove_object(drop.id)

    after = graph.all_objects()
    assert [o.id for o in after] == [keep.id]
