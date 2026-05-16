import pytest

from activegraph import Event


def test_event_is_frozen():
    e = Event(id="evt_001", type="x", payload={})
    with pytest.raises(Exception):
        e.id = "evt_999"  # type: ignore[misc]


def test_to_dict_round_trip_keys():
    e = Event(
        id="evt_001",
        type="goal.created",
        payload={"goal": "x"},
        actor="user",
        frame_id="frame_001",
        caused_by=None,
        timestamp="2026-05-15T10:32:01Z",
    )
    d = e.to_dict()
    assert d["id"] == "evt_001"
    assert d["type"] == "goal.created"
    assert d["payload"] == {"goal": "x"}
    assert d["actor"] == "user"
    assert d["frame_id"] == "frame_001"
    assert d["caused_by"] is None
    assert d["timestamp"] == "2026-05-15T10:32:01Z"
