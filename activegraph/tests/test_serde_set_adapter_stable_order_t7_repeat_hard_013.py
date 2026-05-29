"""T7 repetition hard 013 — docstring↔code drift in ``activegraph.store.serde``.

The module docstring and the ``encode_payload`` error message both document the
strict serialization adapter UNCONDITIONALLY:

    serde.py module docstring:
        "Custom types serialize through the strict adapter below"
    _default() set branch:
        "# Stable order for snapshot-friendliness."  ->  return sorted(o)
    encode_payload() NonSerializableEventError.why:
        "...a strict adapter (Decimal -> string, datetime -> ISO 8601, set ->
         sorted list); anything else is refused at emit-time..."

The documented contract is: a ``set`` payload value serializes to a JSON list
in STABLE (sorted) order. There is no caveat that the set elements must be
mutually comparable.

The code does ``return sorted(o)`` in ``_default``. For a heterogeneous set
(e.g. ``{1, "a"}``) ``sorted`` raises ``TypeError``, which ``encode_payload``
catches and re-raises as ``NonSerializableEventError`` claiming the set "is not
JSON-serializable" — directly contradicting the documented adapter, which lists
``set`` among the types it DOES serialize. The documented behavior (every set
serializes to a stable-ordered JSON list) is not honored.

This test asserts the documented behavior. It FAILS against current code.
"""

from __future__ import annotations

import json

import pytest

from activegraph.store.serde import encode_payload


def test_homogeneous_set_serializes_to_sorted_list() -> None:
    """Baseline: the documented adapter works for a comparable set."""
    out = json.loads(encode_payload({"tags": {"b", "a", "c"}}))
    assert out["tags"] == ["a", "b", "c"]


def test_heterogeneous_set_serializes_to_stable_ordered_list() -> None:
    """DOCUMENTED behavior: a ``set`` payload value serializes to a JSON list.

    The adapter contract (module docstring + encode_payload error message)
    lists ``set -> sorted list`` with no comparability caveat. A set with
    mixed element types is still a set and must serialize, in a stable order,
    rather than being refused as "not JSON-serializable".
    """
    encoded = encode_payload({"mix": {1, "a"}})
    out = json.loads(encoded)
    # Stable order: type-name then value gives a deterministic, JSON-safe order.
    assert sorted(out["mix"], key=lambda v: (type(v).__name__, str(v))) == out["mix"]
    assert set(map(str, out["mix"])) == {"1", "a"}
