import pytest

from activegraph.core.event import Event
from activegraph.core.ids import IDGen


pytestmark = getattr(pytest.mark, "activegraph.core.ids.IDGen.reseed_from_events")


def test_activegraph_core_ids_idgen_reseed_from_events_advances_object_and_event_counters() -> None:
    gen = IDGen()
    events = [
        Event(
            id="evt_005",
            type="object.created",
            payload={"object": {"id": "task#7"}},
            frame_id="frame_003",
        ),
        Event(
            id="evt_002",
            type="object.created",
            payload={"object": {"id": "task#3"}},
        ),
    ]

    gen.reseed_from_events(events)

    assert gen.event() == "evt_006"
    assert gen.object("task") == "task#8"
    assert gen.frame() == "frame_004"


def test_activegraph_core_ids_idgen_reseed_from_events_handles_relation_and_patch_payloads() -> None:
    gen = IDGen()
    events = [
        Event(
            id="evt_001",
            type="relation.created",
            payload={"relation": {"id": "rel_009"}},
        ),
        Event(
            id="evt_002",
            type="patch.proposed",
            payload={"patch": {"id": "patch_004"}},
        ),
        Event(
            id="evt_003",
            type="patch.applied",
            payload={"patch": {"id": "patch_006"}},
        ),
        Event(
            id="evt_004",
            type="patch.rejected",
            payload={"patch_id": "patch_011"},
        ),
    ]

    gen.reseed_from_events(events)

    assert gen.relation() == "rel_010"
    assert gen.patch() == "patch_012"


def test_activegraph_core_ids_idgen_reseed_from_events_never_lowers_existing_counter() -> None:
    gen = IDGen()
    # Advance counters past the events we are about to feed.
    for _ in range(15):
        gen.object("task")
    for _ in range(20):
        gen.event()

    stale_events = [
        Event(
            id="evt_002",
            type="object.created",
            payload={"object": {"id": "task#3"}},
        ),
    ]

    gen.reseed_from_events(stale_events)

    # Stale reseed must not move counters backwards.
    assert gen.object("task") == "task#16"
    assert gen.event() == "evt_021"


def test_activegraph_core_ids_idgen_reseed_from_events_ignores_unrelated_event_types_and_empty_iterable() -> None:
    gen = IDGen()

    gen.reseed_from_events([])
    assert gen.object("task") == "task#1"
    assert gen.event() == "evt_001"
    assert gen.relation() == "rel_001"
    assert gen.patch() == "patch_001"
    assert gen.frame() == "frame_001"

    # An event with an unknown type and no parseable suffixes should be a no-op
    # for the type-specific counters; only the event id suffix advances.
    unrelated = [
        Event(
            id="evt_050",
            type="behavior.completed",
            payload={"object": {"id": "not-a-valid-id"}},
        ),
    ]
    gen.reseed_from_events(unrelated)

    assert gen.event() == "evt_051"
    # Object counter should remain where it was (1 -> next is 2).
    assert gen.object("task") == "task#2"
