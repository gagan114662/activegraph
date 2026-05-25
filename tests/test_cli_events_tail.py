"""Tests for the events tail CLI fixture feature.

Quinn authored these against Sofia's spec. The substring-filter test fails
against Maya's initial implementation because the filter flag was parsed but
ignored.
"""

from __future__ import annotations

from activegraph.cli.events_tail import audit_event_id, tail_events
from activegraph.core.event import Event
from activegraph.store.memory import InMemoryEventStore


def _store() -> InMemoryEventStore:
    store = InMemoryEventStore(run_id="run_events_tail_fixture")
    store.append(Event(id="evt_001", type="alpha.created", payload={"label": "alpha"}, timestamp="2026-05-25T00:00:00Z"))
    store.append(Event(id="evt_002", type="beta.created", payload={"label": "beta"}, caused_by="evt_001", timestamp="2026-05-25T00:01:00Z"))
    store.append(Event(id="evt_003", type="alpha.updated", payload={"label": "alpha", "state": "done"}, caused_by="evt_002", timestamp="2026-05-25T00:02:00Z"))
    return store


def test_events_tail_happy_path_returns_last_n_rows() -> None:
    rows = tail_events(_store(), n=2)
    assert [row["id"] for row in rows] == ["evt_002", "evt_003"]
    assert set(rows[0]) >= {"id", "ts", "kind", "payload", "parent_id"}


def test_events_tail_since_filters_by_timestamp() -> None:
    rows = tail_events(_store(), n=20, since="2026-05-25T00:01:30Z")
    assert [row["id"] for row in rows] == ["evt_003"]


def test_events_tail_substring_filter_limits_rows() -> None:
    rows = tail_events(_store(), n=20, filter_text="beta")
    assert [row["id"] for row in rows] == ["evt_002"]


def test_events_tail_empty_store_returns_no_rows_and_audit_event() -> None:
    store = InMemoryEventStore(run_id="run_empty")
    assert tail_events(store, n=20) == []
    assert audit_event_id(store) == "evt_events_tail_invoked_001"


def test_events_tail_rejects_negative_count() -> None:
    try:
        tail_events(_store(), n=-1)
    except ValueError as error:
        assert "--n" in str(error)
    else:  # pragma: no cover
        raise AssertionError("negative --n must fail")


def test_events_tail_unknown_filter_prints_no_matching_event_rows() -> None:
    rows = tail_events(_store(), n=20, filter_text="does-not-exist")
    assert rows == []
