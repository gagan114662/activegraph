"""Graph primitive tests. Validates CONTRACT #2 (event log truth),
#4 (versioning), #5 (provenance stamping)."""

import pytest

from activegraph import FrozenClock, Graph, IDGen


def _g():
    return Graph(ids=IDGen(), clock=FrozenClock())


def test_add_object_emits_event():
    g = _g()
    o = g.add_object("task", {"title": "x", "status": "open"})
    assert o.id == "task#1"
    assert o.version == 1
    events = g.events
    assert len(events) == 1
    assert events[0].type == "object.created"
    assert events[0].payload["object"]["id"] == "task#1"


def test_provenance_is_stamped_by_runtime_not_behavior():
    g = _g()
    # Even if a "behavior" tries to inject provenance via data, it's stripped.
    o = g.add_object(
        "task",
        {"title": "x", "provenance": {"created_by": "evil"}},
        actor="planner",
    )
    assert o.provenance["created_by"] == "planner"
    # And the data dict doesn't have a stray provenance key.
    assert "provenance" not in o.data


def test_add_relation_emits_event_and_projects():
    g = _g()
    a = g.add_object("task", {"title": "a"})
    b = g.add_object("task", {"title": "b"})
    r = g.add_relation(a.id, b.id, "depends_on")
    assert r.id.startswith("rel_")
    assert r.source == a.id
    assert r.target == b.id
    types = [e.type for e in g.events]
    assert types == ["object.created", "object.created", "relation.created"]


def test_remove_object_cascades_relations():
    g = _g()
    a = g.add_object("task", {})
    b = g.add_object("task", {})
    g.add_relation(a.id, b.id, "depends_on")
    assert len(g.all_relations()) == 1
    g.remove_object(a.id)
    assert g.get_object(a.id) is None
    assert len(g.all_relations()) == 0


def test_query_filters_by_type_and_where():
    g = _g()
    g.add_object("claim", {"text": "x", "confidence": 0.9})
    g.add_object("claim", {"text": "y", "confidence": 0.4})
    g.add_object("task", {"title": "t"})

    high = g.query(object_type="claim", where={"confidence": {">": 0.5}})
    assert len(high) == 1
    assert high[0].data["text"] == "x"


# v1.0.3 #1: graph.objects(type=...) as the canonical query API,
# matching View.objects(type=...) so call sites read the same inside
# and outside behaviors. graph.query(object_type=...) stays as a
# backward-compatible alias.


def test_objects_filters_by_type():
    g = _g()
    g.add_object("claim", {"text": "x"})
    g.add_object("claim", {"text": "y"})
    g.add_object("task", {"title": "t"})

    claims = g.objects(type="claim")
    assert {o.data["text"] for o in claims} == {"x", "y"}
    assert all(o.type == "claim" for o in claims)


def test_objects_filters_by_where():
    g = _g()
    g.add_object("claim", {"text": "x", "confidence": 0.9})
    g.add_object("claim", {"text": "y", "confidence": 0.4})

    high = g.objects(type="claim", where={"confidence": {">": 0.5}})
    assert len(high) == 1
    assert high[0].data["text"] == "x"


def test_objects_with_no_kwargs_returns_every_object():
    # Same semantics as View.objects() with no args: full slice.
    # graph.objects() is a strict superset of graph.all_objects()
    # (which is kept for callers that prefer the explicit-no-filter
    # name and for backward compat).
    g = _g()
    g.add_object("claim", {"text": "x"})
    g.add_object("task", {"title": "t"})

    assert {o.id for o in g.objects()} == {o.id for o in g.all_objects()}


def test_objects_and_query_return_the_same_results():
    g = _g()
    g.add_object("claim", {"text": "x", "confidence": 0.9})
    g.add_object("claim", {"text": "y", "confidence": 0.4})
    g.add_object("task", {"title": "t"})

    new = g.objects(type="claim", where={"confidence": {">": 0.5}})
    old = g.query(object_type="claim", where={"confidence": {">": 0.5}})
    assert [o.id for o in new] == [o.id for o in old]


def test_query_alias_still_works_with_positional_arg():
    # External code that passed the type positionally to query()
    # continues to work — the alias keeps the (object_type=, where=)
    # kwarg shape and the parameter order from v1.0.2.
    g = _g()
    g.add_object("claim", {"text": "x"})
    g.add_object("task", {"title": "t"})

    assert {o.type for o in g.query("claim")} == {"claim"}


def test_neighborhood_walks_to_depth():
    g = _g()
    a = g.add_object("task", {})
    b = g.add_object("task", {})
    c = g.add_object("task", {})
    g.add_relation(a.id, b.id, "depends_on")
    g.add_relation(b.id, c.id, "depends_on")

    objs, rels = g.neighborhood(a.id, depth=1)
    assert {o.id for o in objs} == {a.id, b.id}
    assert len(rels) == 1

    objs2, rels2 = g.neighborhood(a.id, depth=2)
    assert {o.id for o in objs2} == {a.id, b.id, c.id}
    assert len(rels2) == 2


def test_emit_is_only_mutator_for_external_state():
    """Hand-built event is fine; the projector handles it."""
    from activegraph import Event

    g = _g()
    g.emit(
        Event(
            id="evt_999",
            type="object.created",
            payload={
                "object": {
                    "id": "manual#1",
                    "type": "manual",
                    "data": {},
                    "version": 1,
                    "provenance": {},
                },
                "id": "manual#1",
            },
            actor="test",
        )
    )
    assert g.get_object("manual#1") is not None
