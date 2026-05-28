"""T7 medium repetition run 002 — coverage for ``decode_event``.

Target: ``activegraph.store.serde.decode_event`` — previously exercised by no
test file. ``decode_event`` is the inverse of ``encode_event``: it rebuilds a
frozen :class:`~activegraph.core.event.Event` from a stored row, JSON-decoding
the payload and defaulting the optional identity fields.

These tests use real ``Event`` objects and the real ``encode_event`` /
``decode_payload`` machinery — nothing about the serde API under test is
mocked.
"""

from __future__ import annotations

import pytest

from activegraph.core.event import Event
from activegraph.store.errors import CorruptedEventPayloadError
from activegraph.store.serde import decode_event, encode_event


def test_decode_event_round_trips_a_fully_populated_event() -> None:
    """Happy path: an encoded Event with every field set decodes back equal."""
    original = Event(
        id="evt_001",
        type="object.created",
        payload={"name": "Acme", "tags": ["a", "b"], "score": 42, "nested": {"k": 1}},
        actor="maya",
        frame_id="frame_7",
        caused_by="evt_000",
        timestamp="2026-05-28T22:29:17Z",
    )

    row = encode_event(original)
    # The payload travels as a JSON string in the row; decode must rebuild it.
    assert isinstance(row["payload"], str)

    decoded = decode_event(row)

    assert isinstance(decoded, Event)
    assert decoded == original
    assert decoded.payload == original.payload
    assert decoded.payload is not original.payload


def test_decode_event_defaults_optional_fields_when_row_omits_them() -> None:
    """Boundary: a minimal row (only id/type/payload) defaults the optionals.

    ``actor``/``frame_id``/``caused_by`` fall back to ``None`` via ``dict.get``
    and ``timestamp`` falls back to the empty string.
    """
    minimal_row = {"id": "evt_009", "type": "runtime.idle", "payload": "{}"}

    decoded = decode_event(minimal_row)

    assert decoded.id == "evt_009"
    assert decoded.type == "runtime.idle"
    assert decoded.payload == {}
    assert decoded.actor is None
    assert decoded.frame_id is None
    assert decoded.caused_by is None
    assert decoded.timestamp == ""


def test_decode_event_raises_corrupted_payload_error_on_bad_json() -> None:
    """Error behavior: a row whose payload is not valid JSON fails loudly.

    ``decode_event`` delegates to ``decode_payload``, which wraps the JSON
    parse error in a structured :class:`CorruptedEventPayloadError` rather than
    silently skipping the row.
    """
    corrupt_row = {
        "id": "evt_bad",
        "type": "object.created",
        "payload": "{not valid json",
        "timestamp": "2026-05-28T22:29:17Z",
    }

    with pytest.raises(CorruptedEventPayloadError):
        decode_event(corrupt_row)
