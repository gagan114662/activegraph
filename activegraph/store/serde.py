"""Event JSON serialization. CONTRACT v0.5 #4 — JSON only, human-inspectable.

The store persists `event.to_dict()` payloads as JSON. Custom types
serialize through the strict adapter below: anything we cannot encode is
raised as `NonSerializableEventError` at `Graph.emit` time, never silently
dropped or pickled.

Decimals serialize to their canonical string form; datetimes serialize to
ISO 8601. Loading does NOT round-trip these back to Decimal/datetime —
payload semantics stay flat dicts of JSON primitives. Behaviors that need
typed values should keep them as strings in the payload.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from activegraph.core.event import Event


class NonSerializableEventError(TypeError):
    """Raised at emit-time when a payload value cannot be JSON-encoded."""


def _default(o: Any) -> Any:
    if isinstance(o, Decimal):
        return str(o)
    if isinstance(o, (datetime, date)):
        return o.isoformat()
    if isinstance(o, (set, frozenset)):
        # Stable order for snapshot-friendliness.
        return sorted(o)
    raise TypeError(f"object of type {type(o).__name__} is not JSON-serializable")


def encode_payload(payload: dict[str, Any]) -> str:
    """JSON-encode an event payload or raise NonSerializableEventError."""
    try:
        return json.dumps(payload, default=_default, sort_keys=False, ensure_ascii=False)
    except TypeError as e:
        raise NonSerializableEventError(str(e)) from e


def decode_payload(s: str) -> dict[str, Any]:
    """JSON-decode a stored event payload."""
    return json.loads(s)


def encode_event(event: Event) -> dict[str, Any]:
    """Encode an Event to a row-ready dict (payload becomes a JSON string)."""
    return {
        "id": event.id,
        "type": event.type,
        "payload": encode_payload(event.payload),
        "actor": event.actor,
        "frame_id": event.frame_id,
        "caused_by": event.caused_by,
        "timestamp": event.timestamp,
    }


def decode_event(row: dict[str, Any]) -> Event:
    """Decode a stored row back into an Event."""
    return Event(
        id=row["id"],
        type=row["type"],
        payload=decode_payload(row["payload"]),
        actor=row.get("actor"),
        frame_id=row.get("frame_id"),
        caused_by=row.get("caused_by"),
        timestamp=row.get("timestamp", ""),
    )


def validate_event(event: Event) -> None:
    """Fail-fast: ensure the event can be serialized before we mutate state."""
    encode_payload(event.payload)
