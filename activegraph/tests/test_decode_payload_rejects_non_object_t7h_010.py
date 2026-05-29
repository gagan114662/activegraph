"""T7 repeat hard 010 — docstring↔code drift on ``decode_payload``.

``activegraph/store/serde.py::decode_payload`` is documented (and type-
annotated) as::

    def decode_payload(s: str) -> dict[str, Any]:
        '''JSON-decode a stored event payload, or raise
        CorruptedEventPayloadError. ...'''

The contract is therefore binary: the call returns a ``dict`` (a stored
event payload) **or** it raises ``CorruptedEventPayloadError`` for store
contents that aren't a usable payload. The drift: valid-but-non-object
JSON — ``"[1, 2, 3]"``, ``"42"``, ``'"x"'``, ``"null"``, ``"true"`` — is
parseable JSON, so ``json.loads`` does not raise, and ``decode_payload``
hands the caller a ``list``/``int``/``str``/``None``/``bool`` instead of a
``dict``. That silently violates the documented return type. A store row
holding a non-object payload is just as corrupt as one holding non-JSON
bytes (an event payload is always a dict), and per the module's own
rationale a silently-mistyped payload "would corrupt the replay contract."

This test asserts the DOCUMENTED behavior: a dict in, a dict out; anything
that is valid JSON but not a JSON object must raise
``CorruptedEventPayloadError`` (not slip through as a non-dict).
"""

from __future__ import annotations

import pytest

from activegraph.store.serde import CorruptedEventPayloadError, decode_payload


def test_decode_payload_returns_dict_for_object_payload() -> None:
    """A stored JSON object decodes to a dict (the happy path holds)."""
    result = decode_payload('{"k": 1, "nested": {"a": [1, 2]}}')
    assert isinstance(result, dict)
    assert result == {"k": 1, "nested": {"a": [1, 2]}}


@pytest.mark.parametrize(
    "stored",
    [
        "[1, 2, 3]",  # JSON array
        "42",          # JSON number
        '"hello"',    # JSON string
        "null",        # JSON null
        "true",        # JSON bool
    ],
)
def test_decode_payload_rejects_valid_but_non_object_json(stored: str) -> None:
    """Valid JSON that is not an object is a corrupt payload, not a dict.

    The documented contract is "return a dict OR raise
    CorruptedEventPayloadError". A non-object payload satisfies neither
    branch today (it is returned as a non-dict); the documented behavior
    is to raise.
    """
    with pytest.raises(CorruptedEventPayloadError):
        decode_payload(stored)
