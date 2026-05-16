"""Event JSON serialization edge cases."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest

from activegraph import NonSerializableEventError
from activegraph.store.serde import decode_payload, encode_payload, validate_event
from activegraph.core.event import Event


def test_primitive_types_round_trip():
    payload = {"s": "hi", "i": 1, "f": 1.5, "b": True, "n": None, "l": [1, 2]}
    assert decode_payload(encode_payload(payload)) == payload


def test_decimal_encodes_to_string():
    s = encode_payload({"d": Decimal("3.14")})
    assert decode_payload(s) == {"d": "3.14"}


def test_datetime_encodes_to_iso():
    dt = datetime(2026, 5, 15, 10, 32, 1)
    s = encode_payload({"t": dt})
    assert decode_payload(s) == {"t": "2026-05-15T10:32:01"}


def test_date_encodes_to_iso():
    s = encode_payload({"d": date(2026, 5, 15)})
    assert decode_payload(s) == {"d": "2026-05-15"}


def test_set_serializes_to_sorted_list():
    s = encode_payload({"tags": {"b", "a", "c"}})
    assert decode_payload(s) == {"tags": ["a", "b", "c"]}


def test_unsupported_type_raises_non_serializable():
    class X:
        pass

    with pytest.raises(NonSerializableEventError):
        encode_payload({"x": X()})


def test_nested_dicts_and_unicode():
    payload = {"meta": {"name": "héllo 漢字 🚀", "deep": {"k": [None, True]}}}
    assert decode_payload(encode_payload(payload)) == payload


def test_validate_event_rejects_bad_payload():
    class Opaque:
        pass

    ev = Event(id="evt_001", type="x", payload={"k": Opaque()}, timestamp="t")
    with pytest.raises(NonSerializableEventError):
        validate_event(ev)


def test_validate_event_accepts_good_payload():
    ev = Event(id="evt_001", type="x", payload={"k": "v"}, timestamp="t")
    validate_event(ev)  # does not raise
