"""T7 medium 005 coverage for activegraph.store.serde.encode_payload.

encode_payload is the encode-side of the store's JSON serialization contract
(CONTRACT v0.5 #4): it must JSON-encode a payload of primitives, route the
documented custom types (Decimal -> string, datetime/date -> ISO 8601,
set/frozenset -> sorted list) through the strict adapter, and refuse anything
else by raising NonSerializableEventError that names the offending field.

These tests use real payload dicts and the real encode/decode functions -- no
mocks of the API under test.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest

from activegraph.store.serde import (
    NonSerializableEventError,
    decode_payload,
    encode_payload,
)


def test_encode_payload_happy_path_round_trips_primitives() -> None:
    """Happy path: a payload of JSON primitives encodes to a string that
    decodes back to the same dict, with key order preserved (sort_keys=False)."""
    payload = {
        "kind": "goal.created",
        "goal": "ship feature",
        "attempt": 3,
        "ok": True,
        "ratio": 0.5,
        "tags": ["a", "b"],
        "meta": {"nested": {"depth": 2}},
        "nothing": None,
    }

    encoded = encode_payload(payload)

    assert isinstance(encoded, str)
    # Round-trips exactly: encode_payload's output is the store's persisted form.
    assert decode_payload(encoded) == payload
    # sort_keys=False: first-declared key appears before a later one.
    assert encoded.index('"kind"') < encoded.index('"goal"')


def test_encode_payload_strict_adapter_converts_decimal_datetime_and_set() -> None:
    """Boundary: the documented non-JSON types serialize through the strict
    adapter -- Decimal -> canonical string, datetime/date -> ISO 8601,
    set -> sorted list -- rather than being dropped or pickled."""
    payload = {
        "cost": Decimal("1.25"),
        "at": datetime(2026, 5, 28, 12, 30, 0),
        "day": date(2026, 5, 28),
        "labels": {"z", "a", "m"},
    }

    decoded = decode_payload(encode_payload(payload))

    assert decoded["cost"] == "1.25"  # Decimal -> string, not float
    assert decoded["at"] == "2026-05-28T12:30:00"  # datetime -> ISO 8601
    assert decoded["day"] == "2026-05-28"  # date -> ISO 8601
    assert decoded["labels"] == ["a", "m", "z"]  # set -> sorted list (stable order)


def test_encode_payload_raises_non_serializable_for_unsupported_top_level() -> None:
    """Error path: a value the strict adapter does not handle is refused at
    encode time with NonSerializableEventError, and the message names the
    offending top-level field path."""

    class Widget:  # an arbitrary, non-JSON, non-adapter type
        pass

    payload = {"event": "x", "blob": Widget()}

    with pytest.raises(NonSerializableEventError) as exc_info:
        encode_payload(payload)

    err = exc_info.value
    # Multi-inherits TypeError so existing `except TypeError` callers still catch it.
    assert isinstance(err, TypeError)
    assert "blob" in str(err)
    assert err.context["path"] == "blob"
    assert err.context["type"] == "Widget"


def test_encode_payload_reports_nested_path_for_unserializable_value() -> None:
    """Error path (nested): when the offending value is buried inside nested
    dicts/lists, the reported path points at the actual field, not the root."""

    class Widget:
        pass

    payload = {"outer": {"inner": [0, 1, {"bad": Widget()}]}}

    with pytest.raises(NonSerializableEventError) as exc_info:
        encode_payload(payload)

    # _find_non_serializable walks dict.key / list[index] to the culprit.
    assert exc_info.value.context["path"] == "outer.inner[2].bad"
