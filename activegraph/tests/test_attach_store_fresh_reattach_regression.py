"""Regression for Graph.attach_store fresh-graph reattachment.

Found in activegraph/core/graph.py:280: the docstring promises that calling
with a different store is an error after events exist.
Correct behavior should let a graph with no emitted events replace its store.
Current behavior is wrong because it rejects every different second store,
even before any event history could be split.
"""

from activegraph import Graph


def test_attach_store_allows_replacing_store_before_events_exist() -> None:
    graph = Graph()
    first_store = object()
    second_store = object()

    graph.attach_store(first_store)
    graph.attach_store(second_store)

    assert graph.store is second_store
