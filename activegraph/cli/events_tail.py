"""Events-tail CLI command implementation."""

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


def _parse_iso_timestamp(ctx: click.Context, param: click.Parameter, value: str | None) -> str | None:
    if value is None:
        return None
    try:
        _datetime_from_iso(value)
    except ValueError as exc:
        raise click.BadParameter("must be an ISO timestamp", ctx=ctx, param=param) from exc
    return value


def _datetime_from_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _resolve_active_event_store():
    """Open the event store selected by the active CLI environment.

    The command has no positional store arguments by contract, so the active
    store comes from environment state. ``ACTIVEGRAPH_RUN_ID`` is optional for
    SQLite/Postgres URLs that have a discoverable most-recent run.
    """
    url = os.environ.get("ACTIVEGRAPH_STORE_URL") or os.environ.get("ACTIVEGRAPH_STORE")
    run_id = os.environ.get("ACTIVEGRAPH_RUN_ID") or os.environ.get("ACTIVEGRAPH_RUN")
    if not url:
        raise RuntimeError("no active event store")
    if run_id is None:
        run_id = _most_recent_run_id(url)
    if run_id is None:
        raise RuntimeError("no active event store")
    return open_store(url, run_id=run_id)


def _most_recent_run_id(url: str) -> str | None:
    from activegraph.store.url import parse_store_url

    parsed = parse_store_url(url)
    if parsed.scheme == "sqlite":
        from activegraph.store.sqlite import SQLiteEventStore

        return SQLiteEventStore.most_recent_run_id(parsed.sqlite_path or "")
    from activegraph.store.postgres import PostgresEventStore

    return PostgresEventStore.most_recent_run_id(parsed.raw)


def _emit_audit_event(store: Any, *, n: int, since: str | None, filter_text: str | None, as_json: bool) -> None:
    events = list(store.iter_events())
    ids = IDGen()
    ids.reseed_from_events(events)
    store.append(
        Event(
            id=ids.event(),
            type="events_tail_invoked",
            payload={
                "n": n,
                "since": since,
                "filter": filter_text,
                "json": as_json,
            },
            actor="activegraph.cli",
            timestamp=_now_iso(),
        )
    )


def _event_matches(event: Event, *, since: str | None, filter_text: str | None) -> bool:
    if since is not None:
        try:
            if _datetime_from_iso(event.timestamp) < _datetime_from_iso(since):
                return False
        except ValueError:
            if event.timestamp < since:
                return False
    if filter_text is not None and filter_text not in event.type:
        return False
    return True


def _row(event: Event) -> dict[str, Any]:
    return {
        "id": event.id,
        "ts": event.timestamp,
        "kind": event.type,
        "payload": event.payload,
        "parent_id": event.caused_by,
    }


@click.command("tail")
@click.option("--n", "limit", default=20, show_default=True, type=click.IntRange(min=0))
@click.option("--since", callback=_parse_iso_timestamp)
@click.option("--filter", "filter_text")
@click.option("--json", "as_json", is_flag=True)
def cmd_events_tail(
    limit: int,
    since: Optional[str],
    filter_text: Optional[str],
    as_json: bool,
) -> None:
    """Print the last matching active event-store events as JSON lines."""
    try:
        store = _resolve_active_event_store()
    except (InvalidStoreURL, FileNotFoundError, RuntimeError) as exc:
        click.echo(f"no active event store: {exc}", err=True)
        raise SystemExit(1)

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
        if limit:
            matches = matches[-limit:]
        else:
            matches = []
        for event in matches:
            click.echo(json.dumps(_row(event), default=str, separators=(",", ":")))
    finally:
        close = getattr(store, "close", None)
        if close is not None:
            close()
