"""T7 medium repetition run 010 — coverage for ``Event.to_dict``.

Target: ``activegraph.core.event.Event.to_dict`` — previously exercised by no
test file (``pytest --collect-only -k Event.to_dict`` collected 0 tests).

``Event`` is a frozen dataclass that is the append-only record at the heart of
the runtime (CONTRACT #3). ``to_dict`` projects an event into a plain,
serializable mapping with a fixed key set and ordering contract. These tests
exercise the real ``Event`` dataclass — nothing about the API under test is
mocked.

The test function names embed ``activegraph_core_event_Event_to_dict`` so that
``pytest --collect-only -k`` matching either the dotted fully-qualified name or
the underscored symbol form selects them.
"""

from __future__ import annotations

from activegraph.core.event import Event


def test_activegraph_core_event_Event_to_dict_happy_path_fully_populated() -> None:
    """Happy path: every field set projects into the documented key set."""
    event = Event(
        id="evt_001",
        type="object.created",
        payload={"name": "Acme", "tags": ["a", "b"]},
        actor="maya",
        frame_id="frame_7",
        caused_by="evt_000",
        timestamp="2026-05-28T22:29:17Z",
    )

    result = event.to_dict()

    assert result == {
        "id": "evt_001",
        "type": "object.created",
        "payload": {"name": "Acme", "tags": ["a", "b"]},
        "actor": "maya",
        "frame_id": "frame_7",
        "caused_by": "evt_000",
        "timestamp": "2026-05-28T22:29:17Z",
    }
    # The exact key set is part of the serialization contract.
    assert set(result) == {
        "id",
        "type",
        "payload",
        "actor",
        "frame_id",
        "caused_by",
        "timestamp",
    }


def test_activegraph_core_event_Event_to_dict_defaults_when_only_required_fields() -> None:
    """Boundary: with only the required fields set, optionals default through.

    ``payload`` defaults to an empty dict, the three optional identity fields
    (``actor``/``frame_id``/``caused_by``) default to ``None``, and
    ``timestamp`` defaults to the empty string.
    """
    event = Event(id="evt_min", type="runtime.idle")

    result = event.to_dict()

    assert result == {
        "id": "evt_min",
        "type": "runtime.idle",
        "payload": {},
        "actor": None,
        "frame_id": None,
        "caused_by": None,
        "timestamp": "",
    }


def test_activegraph_core_event_Event_to_dict_preserves_payload_object_identity() -> None:
    """Edge case: ``to_dict`` returns the *same* payload object, not a copy.

    The Event docstring is explicit that the payload dict is not deeply frozen
    and is shared by convention. ``to_dict`` must therefore hand back the very
    same mapping instance rather than a defensive copy, so callers observing the
    projection see the live payload.
    """
    payload = {"k": 1, "nested": {"deep": True}}
    event = Event(id="evt_p", type="object.updated", payload=payload)

    result = event.to_dict()

    assert result["payload"] is payload
