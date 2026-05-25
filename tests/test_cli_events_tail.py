"""Adversarial tests for ``activegraph events tail``.

Expected current failure at Maya commit 17b891f:
```
$ pytest -q tests/test_cli_events_tail.py
......F                                                                  [100%]
E       AssertionError: Usage errors must fail before appending the audit event.
E       assert 1 == 2
E        +  where 1 = <Result TypeError("can't compare offset-naive and offset-aware datetimes")>.exit_code
```
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
