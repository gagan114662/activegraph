"""``activegraph events tail`` — print the last N events as NDJSON.

Reference spec: ``docs/specs/events-tail.md`` (T6 extra-hard, opus-4.7 cohort).

The command resolves the active event store from environment state, appends
one ``events_tail_invoked`` audit event through the store's normal append
path, then prints the selected tail window as newline-delimited JSON on
stdout. The audit event participates in the same event stream and is
subject to the caller's ``--since`` and ``--filter`` selection rules.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Optional

import click

from activegraph.core.event import Event
from activegraph.core.ids import IDGen
from activegraph.runtime.runtime import _now_iso
from activegraph.store import InvalidStoreURL, open_store


# Exit codes mirror activegraph.cli.main. Defined locally because main.py
# imports this module at registration time.
_EXIT_GENERIC_ERROR = 1
_EXIT_USAGE_ERROR = 2

_AUDIT_KIND = "events_tail_invoked"
_CLI_ACTOR = "activegraph.cli"
_NO_STORE_MSG = "no active event store"


# ---- flag parsing -------------------------------------------------------


def _parse_iso_since(
    ctx: click.Context,
    param: click.Parameter,
    value: str | None,
) -> str | None:
    """Validate ``--since`` as a tz-aware ISO 8601 timestamp.

    Returns the caller's exact text so the audit payload preserves it
    verbatim (the spec requires the caller's accepted timestamp text).
    """
    if value is None:
        return None
    try:
        parsed = _from_iso(value)
    except ValueError as exc:
        raise click.BadParameter("must be an ISO 8601 timestamp", ctx=ctx, param=param) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise click.BadParameter(
            "must be an ISO 8601 timestamp with timezone offset",
            ctx=ctx,
            param=param,
        )
    return value


def _from_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


# ---- store resolution ---------------------------------------------------


def _resolve_active_store() -> Any:
    """Open the active event store, or raise RuntimeError with the canonical
    "no active event store" message.

    Resolution rules:
      1. URL: ``ACTIVEGRAPH_STORE_URL`` or ``ACTIVEGRAPH_STORE``.
      2. Run id: ``ACTIVEGRAPH_RUN_ID`` or ``ACTIVEGRAPH_RUN``; if absent,
         fall back to the most-recent run id reported by the backing store.
    """
    url = os.environ.get("ACTIVEGRAPH_STORE_URL") or os.environ.get("ACTIVEGRAPH_STORE")
    if not url:
        raise RuntimeError(_NO_STORE_MSG)
    run_id = os.environ.get("ACTIVEGRAPH_RUN_ID") or os.environ.get("ACTIVEGRAPH_RUN")
    if not run_id:
        run_id = _most_recent_run_id(url)
    if not run_id:
        raise RuntimeError(_NO_STORE_MSG)
    return open_store(url, run_id=run_id)


def _most_recent_run_id(url: str) -> str | None:
    from activegraph.store.url import parse_store_url

    parsed = parse_store_url(url)
    if parsed.scheme == "sqlite":
        from activegraph.store.sqlite import SQLiteEventStore

        return SQLiteEventStore.most_recent_run_id(parsed.sqlite_path or "")
    from activegraph.store.postgres import PostgresEventStore

    return PostgresEventStore.most_recent_run_id(parsed.raw)


# ---- audit emission -----------------------------------------------------


def _emit_audit_event(
    store: Any,
    *,
    n: int,
    since: str | None,
    filter_text: str | None,
    as_json: bool,
) -> None:
    """Append the audit event through the store's bound-run append path."""
    existing = list(store.iter_events())
    ids = IDGen()
    ids.reseed_from_events(existing)
    store.append(
        Event(
            id=ids.event(),
            type=_AUDIT_KIND,
            payload={
                "n": n,
                "since": since,
                "filter": filter_text,
                "json": as_json,
            },
            actor=_CLI_ACTOR,
            timestamp=_now_iso(),
        )
    )


# ---- selection ----------------------------------------------------------


def _event_matches(event: Event, *, since: str | None, filter_text: str | None) -> bool:
    if since is not None and not _since_satisfied(event.timestamp, since):
        return False
    if filter_text is not None and filter_text not in event.type:
        return False
    return True


def _since_satisfied(event_ts: str, since: str) -> bool:
    """Return True iff ``event_ts`` is at or after ``since``.

    Both inputs are ISO 8601 strings; ``since`` is validated tz-aware at
    parse time. For events whose stored timestamp is non-ISO, fall back
    to lexicographic compare (correct for the canonical Z-suffixed UTC
    text emitted by ``_now_iso``).
    """
    try:
        return _from_iso(event_ts) >= _from_iso(since)
    except ValueError:
        return event_ts >= since


def _row(event: Event) -> dict[str, Any]:
    """Render one Event as the T6 output row schema."""
    return {
        "id": event.id,
        "ts": event.timestamp,
        "kind": event.type,
        "payload": event.payload,
        "parent_id": event.caused_by,
    }


# ---- click command ------------------------------------------------------


@click.command("tail")
@click.option(
    "--n",
    "limit",
    default=20,
    show_default=True,
    type=click.IntRange(min=0),
    help="Print the last N matching events. Must be >= 0; --n 0 prints zero rows.",
)
@click.option(
    "--since",
    callback=_parse_iso_since,
    default=None,
    metavar="ISO_TS",
    help="Include only events whose timestamp is >= this ISO 8601 timestamp.",
)
@click.option(
    "--filter",
    "filter_text",
    default=None,
    metavar="SUBSTRING",
    help="Include only events whose kind contains this substring (case-sensitive).",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="Machine-readable output. T6 output is always NDJSON; the flag is forward-compat.",
)
def cmd_events_tail(
    limit: int,
    since: Optional[str],
    filter_text: Optional[str],
    as_json: bool,
) -> None:
    """Print the last N events from the active event store as NDJSON.

    Each row is one UTF-8 JSON object with keys ``id``, ``ts``, ``kind``,
    ``payload``, ``parent_id`` followed by a single LF byte. The command
    appends one ``events_tail_invoked`` audit event before reading; that
    audit event is part of the stream and is subject to the same
    ``--since`` and ``--filter`` selection.
    """
    try:
        store = _resolve_active_store()
    except (InvalidStoreURL, FileNotFoundError, RuntimeError) as exc:
        message = str(exc) or _NO_STORE_MSG
        if _NO_STORE_MSG not in message:
            message = f"{_NO_STORE_MSG}: {message}"
        click.echo(message, err=True)
        raise SystemExit(_EXIT_GENERIC_ERROR)

    try:
        _emit_audit_event(
            store,
            n=limit,
            since=since,
            filter_text=filter_text,
            as_json=as_json,
        )
        matches = [
            event
            for event in store.iter_events()
            if _event_matches(event, since=since, filter_text=filter_text)
        ]
        selected = matches[-limit:] if limit > 0 else []
        for event in selected:
            click.echo(json.dumps(_row(event), default=str, separators=(",", ":")))
    finally:
        close = getattr(store, "close", None)
        if callable(close):
            close()
