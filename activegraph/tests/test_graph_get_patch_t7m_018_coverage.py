import pytest

from activegraph.core.graph import Graph
from activegraph.core.patch import Patch


pytestmark = getattr(pytest.mark, "activegraph.core.graph.Graph.get_patch")


def test_activegraph_core_graph_graph_get_patch_returns_proposed_patch() -> None:
    graph = Graph(run_id="run_t7m_018_proposed")
    target = graph.add_object("task", {"title": "ship"})

    patch = graph.propose_patch(
        target=target.id,
        op="merge",
        value={"title": "ship-v2"},
        proposed_by="agent_t7m_018",
        rationale="rename for clarity",
    )

    result = graph.get_patch(patch.id)

    assert isinstance(result, Patch)
    assert result is patch
    assert result.target == target.id
    assert result.status == "proposed"
    assert result.value == {"title": "ship-v2"}


def test_activegraph_core_graph_graph_get_patch_returns_none_for_unknown_id() -> None:
    graph = Graph(run_id="run_t7m_018_missing")
    target = graph.add_object("task", {"title": "present"})
    graph.propose_patch(
        target=target.id,
        op="merge",
        value={"title": "still-present"},
        proposed_by="agent_t7m_018",
    )

    assert graph.get_patch("patch_missing") is None


def test_activegraph_core_graph_graph_get_patch_reflects_applied_status() -> None:
    graph = Graph(run_id="run_t7m_018_applied")
    target = graph.add_object("task", {"title": "draft"})
    patch = graph.propose_patch(
        target=target.id,
        op="merge",
        value={"title": "final"},
        proposed_by="agent_t7m_018",
    )

    graph.apply_patch(patch.id, approved_by="agent_t7m_018")

    result = graph.get_patch(patch.id)
    assert result is not None
    assert result.status == "applied"
