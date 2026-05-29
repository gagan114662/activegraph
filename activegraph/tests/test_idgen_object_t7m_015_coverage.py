"""T7 medium run 015 coverage for activegraph.core.ids.IDGen.object.

`IDGen.object(type_)` is the per-graph object-id generator. The CONTRACT #1
invariant (see ids.py and the README trace `task#1, task#2, claim#3`) is that
the object counter is GLOBAL across types, not per-type — so a second object of
a different type continues the same monotonic sequence. These tests pin that
invariant plus the id format and the type-prefix behaviour.
"""

import pytest

from activegraph import IDGen


pytestmark = getattr(pytest.mark, "activegraph.core.ids.IDGen.object")


def test_activegraph_core_ids_idgen_object_happy_path_uses_type_prefix_and_starts_at_one() -> None:
    ids = IDGen()

    first = ids.object("task")
    second = ids.object("task")

    assert first == "task#1"
    assert second == "task#2"


def test_activegraph_core_ids_idgen_object_counter_is_global_across_types() -> None:
    # CONTRACT #1: the counter is shared across types, so a `claim` created
    # third in the lifetime of the generator is `claim#3`, NOT `claim#1`.
    ids = IDGen()

    a = ids.object("task")
    b = ids.object("task")
    c = ids.object("claim")

    assert (a, b, c) == ("task#1", "task#2", "claim#3")


def test_activegraph_core_ids_idgen_object_is_independent_per_instance() -> None:
    # Boundary: two separate generators do not share the global counter.
    gen_one = IDGen()
    gen_two = IDGen()

    gen_one.object("task")
    gen_one.object("task")

    # Fresh generator starts its own sequence at 1 regardless of the other.
    assert gen_two.object("task") == "task#1"
    assert gen_one.object("task") == "task#3"


def test_activegraph_core_ids_idgen_object_does_not_share_counter_with_other_generators() -> None:
    # Boundary: object() advances ONLY the object counter, leaving the event,
    # relation, patch and frame sequences untouched (they have their own
    # prefixed format), so an id stream stays disjoint by kind.
    ids = IDGen()

    ids.object("task")
    ids.object("note")

    assert ids.event() == "evt_001"
    assert ids.relation() == "rel_001"
    assert ids.object("task") == "task#3"
