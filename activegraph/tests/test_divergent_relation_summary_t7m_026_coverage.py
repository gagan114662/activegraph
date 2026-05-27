import pytest

from activegraph.core.graph import Graph
from activegraph.runtime.diff import DivergentRelation, compute_diff


pytestmark = getattr(pytest.mark, "activegraph.runtime.diff.DivergentRelation.summary")


def _find_divergent_relation(diff, relation_id):
    for divergent in diff.divergent_relations:
        if divergent.id == relation_id:
            return divergent
    raise AssertionError(f"compute_diff did not surface relation {relation_id!r}")


def test_activegraph_runtime_diff_DivergentRelation_summary_only_in_fork_via_compute_diff() -> None:
    parent = Graph(run_id="t7m026-parent-only-in-fork")
    fork = Graph(run_id="t7m026-fork-only-in-fork")
    src = fork.add_object("note", {"text": "src"})
    dst = fork.add_object("note", {"text": "dst"})
    rel = fork.add_relation(source=src.id, target=dst.id, type="cites")

    diff = compute_diff(parent, fork, parent.run_id, fork.run_id)
    divergent = _find_divergent_relation(diff, rel.id)

    summary = divergent.summary()

    assert divergent.in_parent is None
    assert divergent.in_fork is not None
    assert summary == f"{rel.id} only in fork ({src.id} --cites--> {dst.id})"


def test_activegraph_runtime_diff_DivergentRelation_summary_only_in_parent_via_compute_diff() -> None:
    parent = Graph(run_id="t7m026-parent-only-in-parent")
    fork = Graph(run_id="t7m026-fork-only-in-parent")
    src = parent.add_object("note", {"text": "src"})
    dst = parent.add_object("note", {"text": "dst"})
    rel = parent.add_relation(source=src.id, target=dst.id, type="references")

    diff = compute_diff(parent, fork, parent.run_id, fork.run_id)
    divergent = _find_divergent_relation(diff, rel.id)

    summary = divergent.summary()

    assert divergent.in_fork is None
    assert divergent.in_parent is not None
    assert summary == f"{rel.id} only in parent ({src.id} --references--> {dst.id})"


def test_activegraph_runtime_diff_DivergentRelation_summary_differs_when_both_sides_present() -> None:
    divergent = DivergentRelation(
        id="rel-shared-1",
        in_parent={
            "id": "rel-shared-1",
            "source": "obj-a",
            "target": "obj-b",
            "type": "links",
            "data": {"weight": 1},
        },
        in_fork={
            "id": "rel-shared-1",
            "source": "obj-a",
            "target": "obj-b",
            "type": "links",
            "data": {"weight": 9},
        },
    )

    summary = divergent.summary()

    assert summary == "rel-shared-1 differs"


def test_activegraph_runtime_diff_DivergentRelation_summary_constructed_only_in_fork_uses_fork_endpoints() -> None:
    divergent = DivergentRelation(
        id="rel-fork-only-1",
        in_parent=None,
        in_fork={
            "id": "rel-fork-only-1",
            "source": "src-x",
            "target": "tgt-y",
            "type": "annotates",
            "data": {},
        },
    )

    summary = divergent.summary()

    assert summary == "rel-fork-only-1 only in fork (src-x --annotates--> tgt-y)"
