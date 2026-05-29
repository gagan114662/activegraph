"""T7 medium run 006 coverage for activegraph.store.serde.encode_event.

encode_event turns an Event into a row-ready dict whose payload field is a
JSON string (everything else is copied through verbatim). These tests exercise
the happy path (a fully-populated event round-trips through encode_event +
decode_event) and the error/boundary path (a non-serializable payload value is
refused with NonSerializableEventError rather than silently dropped).

Real Event objects and the real serde functions are used — nothing is mocked.
"""

from __future__ import annotations

import json

import pytest

from activegraph.core.event import Event
from activegraph.store.serde import (
    NonSerializableEventError,
    decode_event,
    encode_event,
)


def test_encode_event_happy_path_round_trips_through_decode_event() -> None:
    """A fully-populated event encodes to a row dict and decodes back equal.

    Verifies: payload is serialized to a JSON *string* (not left as a dict),
    every non-payload field is copied verbatim, and decode_event reconstructs
    an equal Event.
    """
    event = Event(
        id="evt-006",
        type="behavior.completed",
        payload={"score": 42, "labels": ["a", "b"], "nested": {"ok": True}},
        actor="maya",
        frame_id="frame-1",
        caused_by="evt-005",
        timestamp="2026-05-28T00:00:00+00:00",
    )

    row = encode_event(event)

    # payload becomes a JSON string; the rest are passed through unchanged.
    assert isinstance(row["payload"], str)
    assert json.loads(row["payload"]) == event.payload
    assert row["id"] == "evt-006"
    assert row["type"] == "behavior.completed"
    assert row["actor"] == "maya"
    assert row["frame_id"] == "frame-1"
    assert row["caused_by"] == "evt-005"
    assert row["timestamp"] == "2026-05-28T00:00:00+00:00"

    # Round-trip: decoding the encoded row reproduces the original event.
    restored = decode_event(row)
    assert restored == event


def test_encode_event_empty_payload_and_optional_fields_default_to_none() -> None:
    """Boundary: an event with an empty payload and no optional metadata.

    Verifies encode_event handles the minimal-event shape: empty payload
    serializes to ``"{}"`` and the optional fields surface as None.
    """
    event = Event(id="evt-min", type="runtime.idle", payload={})

    row = encode_event(event)

    assert row["payload"] == "{}"
    assert row["id"] == "evt-min"
    assert row["type"] == "runtime.idle"
    assert row["actor"] is None
    assert row["frame_id"] is None
    assert row["caused_by"] is None

    restored = decode_event(row)
    assert restored.payload == {}
    assert restored.id == "evt-min"


def test_encode_event_refuses_non_serializable_payload_value() -> None:
    """Error path: a payload value that cannot be JSON-encoded is rejected.

    encode_event must raise NonSerializableEventError (never silently drop or
    pickle) and the message must point at the offending field path so the
    failure is actionable. A bare ``object()`` is not handled by the strict
    ``_default`` adapter (only Decimal/datetime/set are), so it triggers the
    refusal.
    """
    event = Event(
        id="evt-bad",
        type="behavior.completed",
        payload={"good": 1, "bad": object()},
    )

    with pytest.raises(NonSerializableEventError) as excinfo:
        encode_event(event)

    # The error identifies the offending field by path.
    assert "bad" in str(excinfo.value)
    # NonSerializableEventError also IS-A TypeError per its contract.
    assert isinstance(excinfo.value, TypeError)
