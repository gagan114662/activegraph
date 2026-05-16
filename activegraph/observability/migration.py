"""Cross-store migration. CONTRACT v0.8 #5 (revised: transaction-per-run).

Each run migrates in a single transaction against the destination. If a
run fails partway, that run's destination state is unchanged. Writes
use ``INSERT ... ON CONFLICT DO NOTHING`` against ``UNIQUE(id, run_id)``
so re-running after a failure is idempotent. Runs migrate independently
— a bad run does not block the others. A structured per-run report is
returned (and printed by the CLI; ``--json`` dumps the same shape).

Migration is one-directional and explicit. No sync mode, no rollback,
no automatic recovery. To go back, migrate the other direction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from activegraph.store.base import RunRecord
from activegraph.store.url import parse_store_url


@dataclass(frozen=True)
class MigrationRunReport:
    run_id: str
    status: str  # "ok" | "skipped" | "failed"
    events_migrated: int
    error: Optional[str] = None


@dataclass(frozen=True)
class MigrationReport:
    source_url: str
    dest_url: str
    runs: tuple[MigrationRunReport, ...]

    @property
    def ok(self) -> bool:
        return all(r.status != "failed" for r in self.runs)

    @property
    def failures(self) -> tuple[MigrationRunReport, ...]:
        return tuple(r for r in self.runs if r.status == "failed")


def migrate(
    source_url: str,
    dest_url: str,
    *,
    only_run_ids: Optional[list[str]] = None,
    on_progress: Optional[Callable[[MigrationRunReport], None]] = None,
) -> MigrationReport:
    """Copy every run (or a subset) from ``source_url`` into ``dest_url``.

    Args:
        source_url: e.g. ``sqlite:///dev.db``
        dest_url: e.g. ``postgres://localhost/prod``
        only_run_ids: if given, migrate only these runs.
        on_progress: called after each run finishes (success or failure)
            with the ``MigrationRunReport`` for that run.

    Returns:
        A ``MigrationReport``. The overall operation is considered
        successful iff every run's status is ``"ok"`` or ``"skipped"``.
    """
    src = _resolve(source_url)
    dst = _resolve(dest_url)

    run_records = src.list_runs()
    if only_run_ids is not None:
        wanted = set(only_run_ids)
        run_records = [r for r in run_records if r.run_id in wanted]

    reports: list[MigrationRunReport] = []
    for rec in run_records:
        report = _migrate_one_run(src, dst, rec)
        reports.append(report)
        if on_progress is not None:
            on_progress(report)

    return MigrationReport(
        source_url=source_url, dest_url=dest_url, runs=tuple(reports)
    )


# ---- internal helpers ----------------------------------------------------


@dataclass
class _StoreFacade:
    """Uniform surface over SQLite and Postgres for migration.

    Hides the driver-specific call shapes (positional path vs URL) and
    the per-run transaction semantics.
    """

    url: str
    kind: str  # "sqlite" | "postgres"
    target: Any  # path string (sqlite) or URL string (postgres)

    def list_runs(self) -> list[RunRecord]:
        if self.kind == "sqlite":
            from activegraph.store.sqlite import SQLiteEventStore

            return SQLiteEventStore.list_runs(self.target)
        from activegraph.store.postgres import PostgresEventStore

        return PostgresEventStore.list_runs(self.target)

    def open_run(self, run_id: str):
        if self.kind == "sqlite":
            from activegraph.store.sqlite import SQLiteEventStore

            return SQLiteEventStore(self.target, run_id=run_id)
        from activegraph.store.postgres import PostgresEventStore

        return PostgresEventStore(self.target, run_id=run_id)

    def write_run_transactionally(
        self, rec: RunRecord, events: list
    ) -> int:
        """Insert run row + events in one transaction.

        Returns the number of events newly written (idempotent: rerunning
        after a partial failure returns only the count of rows that were
        actually inserted this time).
        """
        if self.kind == "sqlite":
            return _write_run_sqlite(self.target, rec, events)
        return _write_run_postgres(self.target, rec, events)


def _resolve(url: str) -> _StoreFacade:
    parsed = parse_store_url(url)
    if parsed.scheme == "sqlite":
        return _StoreFacade(url=url, kind="sqlite", target=parsed.sqlite_path or "")
    return _StoreFacade(url=url, kind="postgres", target=parsed.raw)


def _migrate_one_run(
    src: _StoreFacade, dst: _StoreFacade, rec: RunRecord
) -> MigrationRunReport:
    src_store = src.open_run(rec.run_id)
    try:
        events = list(src_store.iter_events())
    except Exception as e:
        return MigrationRunReport(
            run_id=rec.run_id,
            status="failed",
            events_migrated=0,
            error=f"read failure: {e}",
        )
    finally:
        src_store.close()

    try:
        n = dst.write_run_transactionally(rec, events)
    except Exception as e:
        return MigrationRunReport(
            run_id=rec.run_id,
            status="failed",
            events_migrated=0,
            error=f"write failure: {e}",
        )

    return MigrationRunReport(
        run_id=rec.run_id, status="ok", events_migrated=n
    )


# ---- driver-specific transactional writers ------------------------------


def _write_run_sqlite(path: str, rec: RunRecord, events: list) -> int:
    """Single-transaction SQLite write with INSERT OR IGNORE for idempotency."""
    import sqlite3

    from activegraph.store.serde import encode_event
    from activegraph.store.sqlite import _ensure_schema

    conn = sqlite3.connect(path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    _ensure_schema(conn)
    n = 0
    try:
        conn.execute("BEGIN")
        conn.execute(
            """
            INSERT INTO runs (run_id, parent_run_id, forked_at_event_id, label, created_at, goal, frame_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id) DO NOTHING
            """,
            (
                rec.run_id,
                rec.parent_run_id,
                rec.forked_at_event_id,
                rec.label,
                rec.created_at,
                rec.goal,
                rec.frame_id,
            ),
        )
        for ev in events:
            row = encode_event(ev)
            cur = conn.execute(
                """
                INSERT INTO events (id, type, actor, payload, frame_id, caused_by, timestamp, run_id)
                VALUES (:id, :type, :actor, :payload, :frame_id, :caused_by, :timestamp, :run_id)
                ON CONFLICT(id, run_id) DO NOTHING
                """,
                {**row, "run_id": rec.run_id},
            )
            if cur.rowcount > 0:
                n += 1
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()
    return n


def _write_run_postgres(url: str, rec: RunRecord, events: list) -> int:
    """Single-transaction Postgres write with ON CONFLICT DO NOTHING."""
    import json

    from activegraph.store.postgres import (
        _EVENT_COLUMNS,
        _ConnectionSource,
        _ensure_schema,
    )

    source = _ConnectionSource(url)
    try:
        _ensure_schema(source)
        with source.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO runs (run_id, parent_run_id, forked_at_event_id, label, created_at, goal, frame_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (run_id) DO NOTHING
                    """,
                    (
                        rec.run_id,
                        rec.parent_run_id,
                        rec.forked_at_event_id,
                        rec.label,
                        rec.created_at,
                        rec.goal,
                        rec.frame_id,
                    ),
                )
                n = 0
                for ev in events:
                    cur.execute(
                        f"""
                        INSERT INTO events ({_EVENT_COLUMNS}, run_id)
                        VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s, %s)
                        ON CONFLICT (id, run_id) DO NOTHING
                        """,
                        (
                            ev.id,
                            ev.type,
                            ev.actor,
                            json.dumps(ev.payload),
                            ev.frame_id,
                            ev.caused_by,
                            ev.timestamp,
                            rec.run_id,
                        ),
                    )
                    if cur.rowcount > 0:
                        n += 1
                return n
    finally:
        source.close()
