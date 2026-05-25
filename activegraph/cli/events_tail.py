"""Implementation for `activegraph events tail`.

This fixture module backs the T6 extra-hard verifier fixtures. It is small,
but it uses the real EventStore protocol rather than a mocked log.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from activegraph.core.event import Event


def _event_timestamp(event: Event) -> str:
    return event.timestamp or ""


def _event_kind(event: Event) -> str:
    return event.type


def _to_output_row(event: Event) -> dict[str, Any]:
    return {
        "id": event.id,
        "ts": _event_timestamp(event),
        "kind": _event_kind(event),
        "payload": event.payload,
        "parent_id": event.caused_by,
    }


def tail_events(store: Any, *, n: int = 20, since: str | None = None, filter_text: str | None = None) -> list[dict[str, Any]]:
    """Return the last matching events and append an invocation audit event."""
    if n < 0:
        raise ValueError("--n must be >= 0")

    events = list(store.iter_events())
    filtered = [event for event in events if not since or _event_timestamp(event) >= since]
    selected = filtered[-n:] if n else []
    rows = [_to_output_row(event) for event in selected]
    audit_id = f"evt_events_tail_invoked_{len(events) + 1:03d}"
    store.append(
        Event(
            id=audit_id,
            type="events_tail_invoked",
            payload={
                "n": n,
                "since": since,
                "filter": filter_text,
                "printed": len(rows),
            },
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
    )
    return rows


def audit_event_id(store: Any) -> str | None:
    """Return the newest events_tail_invoked event id from a store."""
    for event in reversed(list(store.iter_events())):
        if event.type == "events_tail_invoked":
            return event.id
    return None
