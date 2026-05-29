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
from activegraph.errors import StorageError
from activegraph.store.errors import CorruptedEventPayloadError


class NonSerializableEventError(StorageError, TypeError):
    """Raised at emit-time when a payload value cannot be JSON-encoded.

    Multi-inherits :class:`TypeError` so user code that does
    ``except TypeError`` around emit/append calls keeps working.
    Distinct from :class:`CorruptedEventPayloadError` — this is the
    encode-side failure (Python value cannot be made into JSON);
    that one is the decode-side failure (JSON bytes cannot be made
    into a Python value).
    """

    _doc_slug = "non-serializable-event-error"


def _default(o: Any) -> Any:
    if isinstance(o, Decimal):
        return str(o)
    if isinstance(o, (datetime, date)):
        return o.isoformat()
    if isinstance(o, (set, frozenset)):
        # Stable order for snapshot-friendliness. `sorted` alone raises
        # TypeError on a heterogeneous set (mixed, mutually-incomparable
        # element types), which would contradict the documented adapter
        # contract ("set -> sorted list", no comparability caveat). Sort on
        # a (type-name, str) key so any set serializes to a deterministic
        # JSON list. Homogeneous comparable sets keep their natural order.
        try:
            return sorted(o)
        except TypeError:
            return sorted(o, key=lambda v: (type(v).__name__, str(v)))
    raise TypeError(f"object of type {type(o).__name__} is not JSON-serializable")


def encode_payload(payload: dict[str, Any]) -> str:
    """JSON-encode an event payload or raise NonSerializableEventError."""
    try:
        return json.dumps(payload, default=_default, sort_keys=False, ensure_ascii=False)
    except TypeError as e:
        # Try to identify the offending field by walking the payload.
        offender_path, offender_type = _find_non_serializable(payload)
        raise NonSerializableEventError(
            f"event payload field {offender_path!r} is not JSON-serializable "
            f"(type: {offender_type})",
            what_failed=(
                f"While encoding an event payload for the store, the value at "
                f"{offender_path!r} (type {offender_type}) could not be JSON-"
                f"encoded.\n  underlying: {e}"
            ),
            why=(
                "The store persists events as JSON so the audit trail is "
                "human-inspectable and round-trips through any JSON-aware "
                "tool. Custom Python types serialize through a strict "
                "adapter (Decimal → string, datetime → ISO 8601, set → "
                "sorted list); anything else is refused at emit-time rather "
                "than silently pickled or dropped, because a silently-"
                "dropped event would corrupt the replay contract."
            ),
            how_to_fix=(
                f"Convert {offender_path!r} to a JSON primitive before "
                f"emitting. Common fixes:\n"
                f"  - Pydantic model:  payload['{offender_path}'] = model.model_dump()\n"
                f"  - dataclass:       payload['{offender_path}'] = dataclasses.asdict(value)\n"
                f"  - custom object:   payload['{offender_path}'] = str(value)\n"
                f"\n"
                f"If the type really should serialize, add an adapter clause "
                f"to ``_default`` in activegraph/store/serde.py (Decimal and "
                f"datetime are precedents)."
            ),
            context={"path": offender_path, "type": offender_type},
        ) from e


def _find_non_serializable(payload: Any, path: str = "") -> tuple[str, str]:
    """Walk ``payload`` to find the first value that isn't JSON-encodable
    by the strict adapter. Returns ``(path, type_name)``. Falls back to
    ``("<unknown>", "<unknown>")`` if the walk completes without finding
    a culprit (shouldn't happen — encode_payload only calls us after
    json.dumps already raised).
    """
    if isinstance(payload, dict):
        for k, v in payload.items():
            sub = f"{path}.{k}" if path else str(k)
            try:
                json.dumps(v, default=_default)
            except TypeError:
                return _find_non_serializable(v, sub)
        return (path or "<root>", type(payload).__name__)
    if isinstance(payload, list):
        for i, v in enumerate(payload):
            sub = f"{path}[{i}]"
            try:
                json.dumps(v, default=_default)
            except TypeError:
                return _find_non_serializable(v, sub)
        return (path or "<root>", type(payload).__name__)
    return (path or "<root>", type(payload).__name__)


def decode_payload(s: str) -> dict[str, Any]:
    """JSON-decode a stored event payload, or raise CorruptedEventPayloadError.

    Wraps :class:`json.JSONDecodeError` so corrupt store contents fail
    with a structured message rather than bubbling the parser exception.
    The store's ``replay_into`` and ``iter_events`` are the entry points;
    corruption is visible at the call site that triggered the load.
    """
    try:
        decoded = json.loads(s)
    except json.JSONDecodeError as e:
        preview = s if len(s) <= 64 else s[:60] + " ..."
        raise CorruptedEventPayloadError(
            f"event payload could not be decoded as JSON (at column {e.colno})",
            what_failed=(
                f"While reading a stored event payload, the JSON parser failed "
                f"at line {e.lineno}, column {e.colno}:\n"
                f"  {e.msg}\n"
                f"  payload preview: {preview!r}"
            ),
            why=(
                "The store persists every event payload as JSON. A row that "
                "doesn't parse as JSON means the bytes on disk are corrupted, "
                "the store schema is mismatched (someone wrote a non-JSON "
                "format here), or an out-of-band edit damaged the file. The "
                "framework refuses to silently skip the row — that would "
                "make the replay contract unverifiable, and the next fork or "
                "diff would lie about what happened."
            ),
            how_to_fix=(
                "Recover the readable subset of the run by migrating with\n"
                "--skip-corrupted (this skips only the unreadable events and\n"
                "keeps everything else; the destination run is partial but\n"
                "load-bearing events around the corruption are preserved):\n"
                "    activegraph migrate --from <src> --to <new-dst> --skip-corrupted\n"
                "The skipped event ids appear in the per-run report.\n"
                "\n"
                "If you need to inspect the corruption first:\n"
                "    activegraph inspect <store> --tail 50\n"
                "\n"
                "If you have the original payload elsewhere (a previous run,\n"
                "a backup, a log), open the store directly with sqlite3 / psql\n"
                "and repair the row in place — preferable to skip-and-lose.\n"
                "\n"
                "If the corruption is intrinsic and the run is not worth\n"
                "recovering, re-run from the original goal in a fresh store.\n"
                "The store is append-only; partial corruption does not\n"
                "propagate backward in time."
            ),
            context={
                "line": e.lineno,
                "column": e.colno,
                "preview": preview,
                "underlying_msg": e.msg,
            },
        ) from e

    # An event payload is always a JSON object. Valid-but-non-object JSON
    # (an array, number, string, null, bool) parses without raising, but it
    # is not a usable payload — returning it would silently violate the
    # documented `dict[str, Any]` contract and feed a non-dict downstream,
    # corrupting the replay contract exactly the same way unparseable bytes
    # would. Treat it as corruption and fail loudly, like the decode error.
    if not isinstance(decoded, dict):
        preview = s if len(s) <= 64 else s[:60] + " ..."
        raise CorruptedEventPayloadError(
            f"event payload decoded as {type(decoded).__name__}, not a JSON object",
            what_failed=(
                f"While reading a stored event payload, the bytes parsed as "
                f"valid JSON but produced a {type(decoded).__name__} rather "
                f"than an object/dict:\n"
                f"  payload preview: {preview!r}"
            ),
            why=(
                "Every event payload is a JSON object (a dict of fields). A "
                "row that parses as a bare array / number / string / null / "
                "bool is corrupt or schema-mismatched — some non-payload value "
                "was written into the payload column. Handing the caller a "
                "non-dict would let the wrong type flow into replay, fork, and "
                "diff, which would lie about what happened just as a silently "
                "skipped corrupt row would."
            ),
            how_to_fix=(
                "Inspect the offending row and restore the JSON object form:\n"
                "    activegraph inspect <store> --tail 50\n"
                "or open the store directly with sqlite3 / psql and repair the\n"
                "payload column for that event id. If the run is not worth\n"
                "recovering, migrate the readable subset:\n"
                "    activegraph migrate --from <src> --to <new-dst> --skip-corrupted\n"
                "The store is append-only; this corruption does not propagate\n"
                "backward in time."
            ),
            context={
                "decoded_type": type(decoded).__name__,
                "preview": preview,
            },
        )

    return decoded


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
