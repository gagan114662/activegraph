import pytest

from activegraph.core.graph import Graph
from activegraph.runtime.diff import DivergentObject, compute_diff


pytestmark = getattr(pytest.mark, "activegraph.runtime.diff.DivergentObject.summary")


def _find_divergent_object(diff, object_id):
    for divergent in diff.divergent_objects:
        if divergent.id == object_id:
            return divergent
    raise AssertionError(f"compute_diff did not surface object {object_id!r}")


def test_activegraph_runtime_diff_divergent_object_summary_only_in_fork() -> None:
    parent = Graph(run_id="t7m016-parent-only-in-fork")
    fork = Graph(run_id="t7m016-fork-only-in-fork")
    fork_only_obj = fork.add_object("note", {"text": "fork-exclusive"})

    diff = compute_diff(parent, fork, parent.run_id, fork.run_id)
    divergent = _find_divergent_object(diff, fork_only_obj.id)

    summary = divergent.summary()

    assert divergent.in_parent is None
    assert divergent.in_fork is not None
    assert summary == f"{fork_only_obj.id} only in fork"


def test_activegraph_runtime_diff_divergent_object_summary_only_in_parent() -> None:
    parent = Graph(run_id="t7m016-parent-only-in-parent")
    fork = Graph(run_id="t7m016-fork-only-in-parent")
    parent_only_obj = parent.add_object("task", {"title": "parent-exclusive"})

    diff = compute_diff(parent, fork, parent.run_id, fork.run_id)
    divergent = _find_divergent_object(diff, parent_only_obj.id)

    summary = divergent.summary()

    assert divergent.in_fork is None
    assert divergent.in_parent is not None
    assert summary == f"{parent_only_obj.id} only in parent"


def test_activegraph_runtime_diff_divergent_object_summary_differs_renders_versions() -> None:
    divergent = DivergentObject(
        id="obj-shared-1",
        in_parent={"id": "obj-shared-1", "version": 3, "data": {"label": "parent"}},
        in_fork={"id": "obj-shared-1", "version": 7, "data": {"label": "fork"}},
    )

    summary = divergent.summary()

    assert summary == "obj-shared-1 differs (parent v3 ↔ fork v7)"


def test_activegraph_runtime_diff_divergent_object_summary_differs_handles_missing_version_key() -> None:
    divergent = DivergentObject(
        id="obj-shared-2",
        in_parent={"id": "obj-shared-2", "data": {"label": "parent"}},
        in_fork={"id": "obj-shared-2", "data": {"label": "fork"}},
    )

    summary = divergent.summary()

    assert summary == "obj-shared-2 differs (parent vNone ↔ fork vNone)"
