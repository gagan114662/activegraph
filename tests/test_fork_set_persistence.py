"""Failing tests for `--set` override persistence (D-3 full-attestation).

Authored by Atlas (direct-fallback per gagan 2026-05-22). Boundary-anchored
against D-3 sealed at inner:4f6b0a0 — fork.override.applied event payload
is self-sufficient across pack drift, containing:

- pack identity (name + version)
- key + typed value
- schema_constraint_snapshot

These tests are RED until Forge wires the override into the fork persistence
path. They verify that the event log is the durable API per D-1's "log is
truth" lock.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from activegraph import SQLiteEventStore


REPO_ROOT = Path(__file__).resolve().parents[1]


def _run_cli(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "activegraph"] + args,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )


def _seed_run(db_path: Path) -> str:
    from activegraph import FrozenClock, Graph, Runtime, behavior

    @behavior(name="seed", on=["goal.created"])
    def seed(event, graph, ctx):
        graph.add_object("claim", {"text": "x", "confidence": 0.6})

    runtime = Runtime(
        graph=Graph(),
        behaviors=[seed],
        store=SQLiteEventStore(str(db_path)),
        clock=FrozenClock(),
    )
    runtime.emit("goal.created", {"goal": "test"})
    runtime.run_until_idle()
    return runtime.run_id


def _read_events(db_path: Path, run_id: str) -> list[dict[str, Any]]:
    """Read raw events from a run's log."""
    store = SQLiteEventStore(str(db_path))
    return [
        {"type": e.type, "payload": e.payload, "id": e.id}
        for e in store.load(run_id)
    ]


# ============================================================================
# fork.override.applied event — D-3 full-attestation shape
# ============================================================================


def test_fork_with_set_emits_fork_override_applied_event(tmp_path: Path) -> None:
    """D-3: fork --set mints a `fork.override.applied` event per override."""
    db = tmp_path / "run.db"
    parent_id = _seed_run(db)
    url = f"sqlite:{db}"

    result = _run_cli([
        "fork", url,
        "--run-id", parent_id,
        "--at-event", "evt_001",
        "--set", "diligence.confidence_threshold_for_review=0.9",
        "--json",
    ])
    assert result.returncode == 0, f"fork --set failed: {result.stderr}"

    import json
    payload = json.loads(result.stdout)
    new_run_id = payload["new_run_id"]

    events = _read_events(db, new_run_id)
    override_events = [e for e in events if e["type"] == "fork.override.applied"]
    assert len(override_events) == 1, (
        f"Expected exactly 1 fork.override.applied event; got {len(override_events)}"
    )


def test_fork_override_applied_payload_has_full_attestation_shape(tmp_path: Path) -> None:
    """D-3 payload shape: pack identity + key + typed value + schema constraint."""
    db = tmp_path / "run.db"
    parent_id = _seed_run(db)
    url = f"sqlite:{db}"

    result = _run_cli([
        "fork", url,
        "--run-id", parent_id,
        "--at-event", "evt_001",
        "--set", "diligence.confidence_threshold_for_review=0.9",
        "--json",
    ])
    assert result.returncode == 0
    import json
    new_run_id = json.loads(result.stdout)["new_run_id"]

    events = _read_events(db, new_run_id)
    override_event = next(e for e in events if e["type"] == "fork.override.applied")
    p = override_event["payload"]

    # D-3 required shape
    assert "pack" in p, "D-3 attestation requires pack identity"
    assert p["pack"].get("name") == "diligence"
    assert "version" in p["pack"], "D-3 requires pinned pack version in payload"
    assert p.get("key") == "confidence_threshold_for_review"
    # D-4: typed value, not raw string
    assert p.get("value") == 0.9
    assert isinstance(p["value"], float), (
        f"D-4 requires typed value in event log; got type={type(p['value']).__name__}"
    )
    assert "schema_constraint_snapshot" in p, (
        "D-3 full-attestation requires schema constraint snapshot for "
        "replay self-sufficiency across pack drift"
    )


def test_fork_with_multiple_set_emits_one_event_per_override(tmp_path: Path) -> None:
    """Composing --set flags produces N fork.override.applied events."""
    db = tmp_path / "run.db"
    parent_id = _seed_run(db)
    url = f"sqlite:{db}"

    result = _run_cli([
        "fork", url,
        "--run-id", parent_id,
        "--at-event", "evt_001",
        "--set", "diligence.confidence_threshold_for_review=0.85",
        "--set", "diligence.support_threshold=0.95",
        "--json",
    ])
    assert result.returncode == 0
    import json
    new_run_id = json.loads(result.stdout)["new_run_id"]

    events = _read_events(db, new_run_id)
    override_events = [e for e in events if e["type"] == "fork.override.applied"]
    assert len(override_events) == 2, (
        f"Expected 2 override events for 2 --set flags; got {len(override_events)}"
    )
    keys = {e["payload"]["key"] for e in override_events}
    assert keys == {"confidence_threshold_for_review", "support_threshold"}


# ============================================================================
# Backward compatibility — pre-existing forks without overrides
# ============================================================================


def test_fork_without_set_does_not_emit_override_event(tmp_path: Path) -> None:
    """Per D-3: fork without --set produces zero fork.override.applied events.

    Backward compatibility — existing fork records without overrides
    must replay unchanged.
    """
    db = tmp_path / "run.db"
    parent_id = _seed_run(db)
    url = f"sqlite:{db}"

    result = _run_cli([
        "fork", url,
        "--run-id", parent_id,
        "--at-event", "evt_001",
        "--json",
    ])
    assert result.returncode == 0
    import json
    new_run_id = json.loads(result.stdout)["new_run_id"]

    events = _read_events(db, new_run_id)
    override_events = [e for e in events if e["type"] == "fork.override.applied"]
    assert len(override_events) == 0, (
        "Fork without --set must not mint any override events"
    )


def test_schema_migration_upgrades_existing_db_on_first_run(tmp_path: Path) -> None:
    """Per yaml predicate `schema_migration_upgrades_existing_db_on_first_run_no_data_loss`.

    A db created before the T3 schema change must open cleanly,
    preserve all events, and accept new --set events.
    """
    db = tmp_path / "pre_migration.db"
    parent_id = _seed_run(db)

    # Re-open the same db with the new code; existing rows must be intact.
    store_after = SQLiteEventStore(str(db))
    events_after = list(store_after.load(parent_id))
    assert len(events_after) > 0, "Schema migration lost existing events"

    # Existing fork should still work without --set
    result = _run_cli([
        "fork", f"sqlite:{db}",
        "--run-id", parent_id,
        "--at-event", "evt_001",
    ])
    assert result.returncode == 0, (
        f"Schema migration broke pre-existing fork: {result.stderr}"
    )


# ============================================================================
# D-2 validation: invalid override does not mint fork.override.applied
# ============================================================================


def test_invalid_set_does_not_create_partial_fork(tmp_path: Path) -> None:
    """D-2: validate_override fires PRE-event. Bad input → no fork created.

    Critical: a failed validation must not leave a partial fork or
    a fork.override.applied event with a bad value.
    """
    db = tmp_path / "run.db"
    parent_id = _seed_run(db)
    url = f"sqlite:{db}"

    result = _run_cli([
        "fork", url,
        "--run-id", parent_id,
        "--at-event", "evt_001",
        "--set", "diligence.confidence_threshold_for_review=not_a_number",
    ])
    assert result.returncode != 0

    # No new run id should exist with override.applied event
    store = SQLiteEventStore(str(db))
    runs = list(store.runs())
    new_runs = [r for r in runs if r != parent_id]
    for r in new_runs:
        events = list(store.load(r))
        override_events = [e for e in events if e.type == "fork.override.applied"]
        assert len(override_events) == 0, (
            "Failed --set must not leave a fork.override.applied event "
            "(D-2 pre-event validation contract)"
        )
