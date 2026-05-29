"""T7 repeat-hard 019 — docstring/comment↔code drift in ``Graph.emit``.

`activegraph.core.graph.Graph.emit` documents a fail-fast serialization
invariant in its body comment (CONTRACT v0.5 #4):

    # Fail-fast serialization check at emit time so bad payloads never
    # land in the in-memory log either (CONTRACT v0.5 #4).
    if self._store is not None:
        from activegraph.store.serde import validate_event
        validate_event(event)

The phrase **"never land in the in-memory log *either*"** is the documented
behavior: the serialization check exists precisely so a non-serializable
payload is rejected at `emit()` time *regardless of whether a store is
attached* — the in-memory log is supposed to stay clean even for a store-less
graph (the common in-memory / test mode created by `Graph()`).

The bug: the `validate_event(event)` call is nested **inside**
`if self._store is not None:`. So when no store is attached, validation is
skipped entirely — a non-serializable payload sails past the check, gets
appended to `self._events`, and is projected. The in-memory log ends up
holding exactly the "bad payload" the comment says can "never land in the
in-memory log either". The persistence path (with a store) honors the
contract; the store-less path silently violates it.

These tests assert the DOCUMENTED behavior on a store-less graph: emitting a
non-serializable payload must raise (and must NOT have landed in the log).
They FAIL against the current code (which only validates when a store is
attached) and PASS once `validate_event` runs unconditionally at emit time.
"""

from __future__ import annotations

import pytest

from activegraph.core.event import Event
from activegraph.core.graph import Graph
from activegraph.store.serde import NonSerializableEventError


class _Opaque:
    """A value with no JSON representation — not a str/number/bool/None/list/dict,
    not a Decimal/datetime/set the serde adapter knows how to coerce."""


def _bad_event() -> Event:
    return Event(
        id="evt_001",
        type="custom.event",
        payload={"value": _Opaque()},
        timestamp="2026-01-01T00:00:00Z",
    )


def test_emit_without_store_rejects_non_serializable_payload() -> None:
    # Store-less graph: the documented invariant says the bad payload must
    # never land in the in-memory log either, so emit() must fail fast.
    g = Graph()
    assert g._store is None  # precondition: no store attached
    with pytest.raises(NonSerializableEventError):
        g.emit(_bad_event())


def test_emit_without_store_leaves_log_clean_after_rejection() -> None:
    # And the bad payload must NOT have landed in the in-memory log.
    g = Graph()
    assert g._store is None
    before = len(g._events)
    with pytest.raises(NonSerializableEventError):
        g.emit(_bad_event())
    assert len(g._events) == before, (
        "non-serializable payload landed in the in-memory log on a store-less "
        "graph — violates the 'never land in the in-memory log either' invariant"
    )


def test_emit_without_store_still_accepts_good_payload() -> None:
    # The fix must NOT break the normal store-less emit path: a serializable
    # payload still lands in the log and is returned.
    g = Graph()
    good = Event(
        id="evt_001",
        type="custom.event",
        payload={"value": 42, "name": "ok"},
        timestamp="2026-01-01T00:00:00Z",
    )
    out = g.emit(good)
    assert out is good
    assert g._events[-1] is good
