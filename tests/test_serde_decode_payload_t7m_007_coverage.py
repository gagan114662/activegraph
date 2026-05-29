"""T7 medium run 007 — coverage for activegraph.store.serde.decode_payload.

decode_payload is the decode-side half of the store's JSON serialization
contract (CONTRACT v0.5 #4). It JSON-decodes a stored event payload string
back into a dict, and wraps json.JSONDecodeError in a structured
CorruptedEventPayloadError so a corrupt store row fails loudly with
recovery guidance rather than bubbling a raw parser exception.

These tests exercise distinct configurations of the API:
  - happy path: well-formed JSON object decodes to the expected dict
  - round-trip: encode_payload -> decode_payload preserves JSON primitives
  - error path: corrupt JSON raises CorruptedEventPayloadError with the
    documented structured context (line / column / preview / underlying_msg)
  - boundary: a long corrupt payload is truncated to a 64-char preview

No mocks of the API under test — decode_payload is pure and called directly.
"""

from __future__ import annotations

import pytest

from activegraph.store.errors import CorruptedEventPayloadError
from activegraph.store.serde import decode_payload, encode_payload


def test_decode_payload_happy_path_decodes_nested_json_object() -> None:
    """A well-formed JSON object string decodes to the equivalent dict,
    preserving nested lists and primitive types."""
    raw = '{"actor": "maya", "count": 3, "tags": ["a", "b"], "ok": true}'

    result = decode_payload(raw)

    assert result == {
        "actor": "maya",
        "count": 3,
        "tags": ["a", "b"],
        "ok": True,
    }
    # JSON booleans must become Python bool, not int.
    assert result["ok"] is True


def test_decode_payload_round_trips_with_encode_payload() -> None:
    """encode_payload followed by decode_payload is identity for a payload
    of JSON primitives — the two halves of the serde contract agree."""
    payload = {
        "name": "event-007",
        "nested": {"depth": 2, "items": [1, 2, 3]},
        "empty": {},
        "flag": False,
        "nothing": None,
    }

    encoded = encode_payload(payload)
    decoded = decode_payload(encoded)

    assert decoded == payload


def test_decode_payload_raises_corrupted_error_with_structured_context() -> None:
    """Invalid JSON raises CorruptedEventPayloadError (not a bare
    JSONDecodeError), and the error carries the documented structured
    context fields plus a human-readable column reference."""
    corrupt = "{not valid json"

    with pytest.raises(CorruptedEventPayloadError) as excinfo:
        decode_payload(corrupt)

    err = excinfo.value
    # The structured context is the contract the store and CLI rely on.
    assert err.context is not None
    assert set(err.context) >= {"line", "column", "preview", "underlying_msg"}
    assert err.context["line"] == 1
    assert err.context["preview"] == corrupt
    # Short payloads are previewed verbatim (no truncation marker).
    assert "..." not in err.context["preview"]
    # The summary message surfaces the failing column for quick triage.
    assert "column" in str(err)


def test_decode_payload_truncates_preview_for_long_corrupt_payload() -> None:
    """A corrupt payload longer than 64 chars is truncated in the preview
    to the first 60 chars plus an ellipsis marker, so error output stays
    bounded regardless of row size."""
    # 100 opening braces is invalid JSON and well over the 64-char cutoff.
    corrupt = "{" * 100

    with pytest.raises(CorruptedEventPayloadError) as excinfo:
        decode_payload(corrupt)

    preview = excinfo.value.context["preview"]
    assert preview == corrupt[:60] + " ..."
    assert len(preview) == 64
    assert preview.endswith(" ...")
