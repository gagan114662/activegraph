import pytest

from activegraph.behaviors.base import Behavior
from activegraph.core.graph import Graph
from activegraph.runtime.view_builder import build_view


pytestmark = getattr(pytest.mark, "activegraph.runtime.view_builder.build_view")


def _noop(event, graph, ctx) -> None:
    return None


def test_activegraph_runtime_view_builder_build_view_defaults_to_graph_scope() -> None:
    graph = Graph(run_id="view-builder-default")
    source = graph.add_object("person", {"name": "Ada"})
    target = graph.add_object("company", {"name": "ActiveGraph"})
    relation = graph.add_relation(source.id, target.id, "works_at")
    behavior = Behavior(name="default-view", fn=_noop)

    view = build_view(behavior, graph.events[-1], graph)

    assert view.objects() == [source, target]
    assert view.relations() == [relation]
    assert view.events() == graph.events[-50:]


def test_activegraph_runtime_view_builder_build_view_applies_include_types_and_recent_events() -> None:
    graph = Graph(run_id="view-builder-filtered")
    graph.add_object("person", {"name": "Ada"})
    task = graph.add_object("task", {"title": "Review"})
    behavior = Behavior(
        name="filtered-view",
        fn=_noop,
        view_spec={"include_types": ["task"], "recent_events": 0},
    )

    view = build_view(behavior, graph.events[-1], graph)

    assert view.objects() == [task]
    assert view.events() == []
