"""Adversarial tests for ``activegraph events tail`` (Quinn, opus-4.7 cohort).

Target: Maya commit 78728a9 (T6 extra-hard, opus-4.7 cohort).

The suite covers each clause of ``docs/specs/events-tail.md`` that is
mechanically checkable from the CLI surface:

* NDJSON row schema (id, ts, kind, payload, parent_id) with no extra keys.
* ``--n`` as a suffix selector that includes the audit event when it matches.
* ``--since`` as an inclusive ISO 8601 ``>=`` comparison.
* ``--filter`` as a case-sensitive literal substring on event kind.
* ``--n 0`` is legal, emits the audit event, prints zero rows.
* Audit payload preserves effective flag values verbatim (defaults applied).
* Usage errors (malformed ``--n``, date-only ``--since``) exit 2 before the
  audit event is appended.
* No-active-store and unreachable-store paths both emit the canonical
  ``no active event store`` stderr message and exit 1.

The last test (``test_unreachable_sqlite_path_reports_no_active_event_store``)
is the focused adversarial probe: Maya's ``_resolve_active_store`` only
catches ``(InvalidStoreURL, FileNotFoundError, RuntimeError)``, so a SQLite
URL whose parent directory does not exist raises an uncaught
``sqlite3.OperationalError`` and the CLI exits with an empty stderr instead
of the spec-required ``no active event store`` message.
"""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from activegraph.cli.main import EXIT_GENERIC_ERROR, EXIT_OK, EXIT_USAGE_ERROR, cli
from activegraph.core.event import Event
from activegraph.store.sqlite import SQLiteEventStore


RUN_ID = "run_events_tail"


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def active_store(tmp_path, monkeypatch):
    path = tmp_path / "events.sqlite"
    store = SQLiteEventStore(str(path), run_id=RUN_ID)
    store.upsert_run(created_at="2026-05-25T14:59:00Z")
    store.close()
    monkeypatch.setenv("ACTIVEGRAPH_STORE_URL", f"sqlite:///{path}")
    monkeypatch.setenv("ACTIVEGRAPH_RUN_ID", RUN_ID)
    return path


def _append(path, *events: Event) -> None:
    store = SQLiteEventStore(str(path), run_id=RUN_ID)
    for event in events:
        store.append(event)
    store.close()


def _events(path) -> list[Event]:
    store = SQLiteEventStore(str(path), run_id=RUN_ID)
    try:
        return list(store.iter_events())
    finally:
        store.close()


def _rows(output: str) -> list[dict]:
    return [json.loads(line) for line in output.splitlines() if line.strip()]


def _event(
    event_id: str,
    kind: str,
    ts: str,
    payload: dict,
    *,
    parent_id: str | None = None,
) -> Event:
    return Event(
        id=event_id,
        type=kind,
        payload=payload,
        caused_by=parent_id,
        timestamp=ts,
    )


def test_default_tail_emits_json_lines_with_required_row_schema(
    runner: CliRunner, active_store
) -> None:
    _append(
        active_store,
        _event(
            "evt_001",
            "object.created",
            "2026-05-25T15:00:00Z",
            {"name": "alpha"},
            parent_id="evt_000",
        ),
    )

    result = runner.invoke(cli, ["events", "tail"])

    assert result.exit_code == EXIT_OK, result.output
    rows = _rows(result.output)
    assert rows[0] == {
        "id": "evt_001",
        "ts": "2026-05-25T15:00:00Z",
        "kind": "object.created",
        "payload": {"name": "alpha"},
        "parent_id": "evt_000",
    }
    assert rows[1]["kind"] == "events_tail_invoked"
    assert set(rows[1]) == {"id", "ts", "kind", "payload", "parent_id"}


def test_n_returns_last_matching_events_and_includes_matching_audit(
    runner: CliRunner, active_store
) -> None:
    _append(
        active_store,
        _event("evt_001", "object.created", "2026-05-25T15:00:00Z", {}),
        _event("evt_002", "events.user_action", "2026-05-25T15:01:00Z", {}),
        _event("evt_003", "events.user_done", "2026-05-25T15:02:00Z", {}),
    )

    result = runner.invoke(cli, ["events", "tail", "--n", "2", "--filter", "events"])

    assert result.exit_code == EXIT_OK, result.output
    rows = _rows(result.output)
    assert [row["kind"] for row in rows] == ["events.user_done", "events_tail_invoked"]
    assert rows[-1]["payload"]["n"] == 2
    assert rows[-1]["payload"]["filter"] == "events"


def test_since_filters_using_iso_timestamps(runner: CliRunner, active_store) -> None:
    _append(
        active_store,
        _event("evt_001", "object.created", "2026-05-25T14:59:59Z", {"n": 1}),
        _event("evt_002", "object.updated", "2026-05-25T15:00:00Z", {"n": 2}),
        _event("evt_003", "object.deleted", "2026-05-25T15:00:01Z", {"n": 3}),
    )

    result = runner.invoke(
        cli, ["events", "tail", "--since", "2026-05-25T15:00:00Z"]
    )

    assert result.exit_code == EXIT_OK, result.output
    rows = _rows(result.output)
    assert [row["kind"] for row in rows[:2]] == ["object.updated", "object.deleted"]
    assert rows[-1]["kind"] == "events_tail_invoked"


def test_filter_is_literal_substring_over_event_kind(
    runner: CliRunner, active_store
) -> None:
    _append(
        active_store,
        _event("evt_001", "object.created", "2026-05-25T15:00:00Z", {}),
        _event("evt_002", "object.create", "2026-05-25T15:01:00Z", {}),
        _event("evt_003", "tool.created", "2026-05-25T15:02:00Z", {}),
    )

    result = runner.invoke(cli, ["events", "tail", "--filter", "object.created"])

    assert result.exit_code == EXIT_OK, result.output
    assert [row["kind"] for row in _rows(result.output)] == ["object.created"]


def test_no_active_store_exits_nonzero_with_clear_stderr(
    runner: CliRunner, monkeypatch
) -> None:
    monkeypatch.delenv("ACTIVEGRAPH_STORE_URL", raising=False)
    monkeypatch.delenv("ACTIVEGRAPH_STORE", raising=False)
    monkeypatch.delenv("ACTIVEGRAPH_RUN_ID", raising=False)
    monkeypatch.delenv("ACTIVEGRAPH_RUN", raising=False)

    result = runner.invoke(cli, ["events", "tail"])

    assert result.exit_code == EXIT_GENERIC_ERROR
    assert "no active event store" in result.output


def test_malformed_n_is_rejected_before_audit_append(
    runner: CliRunner, active_store
) -> None:
    result = runner.invoke(cli, ["events", "tail", "--n", "-1"])

    assert result.exit_code == EXIT_USAGE_ERROR
    assert [event.type for event in _events(active_store)] == []


def test_date_only_since_is_rejected_before_audit_append(
    runner: CliRunner, active_store
) -> None:
    result = runner.invoke(cli, ["events", "tail", "--since", "2026-05-25"])

    assert result.exit_code == EXIT_USAGE_ERROR, (
        "Usage errors must fail before appending the audit event."
    )
    assert [event.type for event in _events(active_store)] == []


def test_n_zero_emits_audit_event_but_prints_no_rows(
    runner: CliRunner, active_store
) -> None:
    """``--n 0`` is legal: zero rows printed, but the audit event MUST still
    be appended to the store (spec selection step 3 is unconditional on N)."""
    _append(
        active_store,
        _event("evt_001", "object.created", "2026-05-25T15:00:00Z", {}),
    )

    result = runner.invoke(cli, ["events", "tail", "--n", "0"])

    assert result.exit_code == EXIT_OK, result.output
    assert _rows(result.output) == []
    kinds = [event.type for event in _events(active_store)]
    assert kinds == ["object.created", "events_tail_invoked"]


def test_audit_payload_records_effective_flag_values(
    runner: CliRunner, active_store
) -> None:
    """The audit event's payload must record effective values after defaults
    are applied, and must preserve the caller's accepted ``--since`` text."""
    since_text = "2026-05-25T15:00:00+00:00"

    result = runner.invoke(
        cli,
        [
            "events",
            "tail",
            "--n",
            "5",
            "--since",
            since_text,
            "--filter",
            "object",
            "--json",
        ],
    )

    assert result.exit_code == EXIT_OK, result.output
    stored = _events(active_store)
    audit = [e for e in stored if e.type == "events_tail_invoked"]
    assert len(audit) == 1, [e.type for e in stored]
    payload = audit[0].payload
    assert payload == {
        "n": 5,
        "since": since_text,
        "filter": "object",
        "json": True,
    }


def test_unreachable_sqlite_path_reports_no_active_event_store(
    runner: CliRunner, monkeypatch, tmp_path
) -> None:
    """Adversarial: a SQLite URL whose parent directory does not exist must
    surface as the canonical ``no active event store`` stderr message with
    exit code 1 — not as an uncaught ``sqlite3.OperationalError`` traceback.

    Spec ``### No Store``: "must write a clear stderr message containing the
    substring `no active event store` and exit with the CLI's generic error
    code `1`." A bad URL is, from the operator's perspective, the same
    failure class as an unset URL: there is no active store.

    Maya commit 78728a9 catches ``(InvalidStoreURL, FileNotFoundError,
    RuntimeError)`` in ``_resolve_active_store`` but ``sqlite3.connect``
    raises ``sqlite3.OperationalError`` on a missing parent directory, which
    is unrelated to the three caught classes. The exception escapes and the
    CLI exits with the wrong stderr surface.
    """
    bad_path = tmp_path / "does" / "not" / "exist" / "events.sqlite"
    monkeypatch.setenv("ACTIVEGRAPH_STORE_URL", f"sqlite:///{bad_path}")
    monkeypatch.delenv("ACTIVEGRAPH_STORE", raising=False)
    monkeypatch.delenv("ACTIVEGRAPH_RUN_ID", raising=False)
    monkeypatch.delenv("ACTIVEGRAPH_RUN", raising=False)

    result = runner.invoke(cli, ["events", "tail"])

    assert result.exit_code == EXIT_GENERIC_ERROR, (
        f"expected exit 1 with clean stderr, got exit={result.exit_code} "
        f"exception={result.exception!r}"
    )
    assert "no active event store" in result.output, (
        f"expected canonical 'no active event store' stderr; got {result.output!r}"
    )
