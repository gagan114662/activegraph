import pytest

from activegraph.core.graph import Graph
from activegraph.store.base import replay_into


pytestmark = getattr(pytest.mark, "activegraph.store.base.replay_into")


def test_activegraph_store_base_replay_into_rebuilds_graph_state() -> None:
    source = Graph(run_id="source-run")
    created = source.add_object("note", {"text": "hello"})

    target = Graph(run_id="target-run")

    replayed = replay_into(target, source.events)

    assert replayed == len(source.events)
    assert target.get_object(created.id) == created
    assert target.replayed_ids == {event.id for event in source.events}


def test_activegraph_store_base_replay_into_accepts_empty_iterable() -> None:
    target = Graph(run_id="target-run")

    replayed = replay_into(target, iter(()))

    assert replayed == 0
    assert target.events == []
    assert target.replayed_ids == frozenset()
