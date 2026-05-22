"""Failing tests for `activegraph fork --set <pack>.<key>=<value>` CLI surface.

Authored by Atlas (direct-fallback per gagan 2026-05-22 — Test Owner
silent-turn at app 0-active). Boundary-anchored against the sealed
T3 amendments:

- D-1 LOCKED inner:27d488b — monotonic-only replay; conflicting set
  with different value raises ReplayDivergenceError, same-value
  re-set is idempotent
- D-2 sealed inner:b16a308 + inner:2dfa58c — reject at fork-creation
  pre-event via `validate_override(key, value, pack)` raising
  InvalidOverrideError before fork.override.applied is minted
- D-3 sealed inner:4f6b0a0 — full-attestation event payload with
  pack identity + typed value + schema constraint snapshot
- D-4 sealed inner:6e167ae — Pydantic-schema-driven coercion via
  Pack.settings_schema field validators; raw string in CLI, typed
  value in event log

These tests are deliberately RED until Forge ships the implementation.
They bind the CLI surface to the sealed contract — no Python-API
workaround. Per GAUNTLET T3 acceptance: the
`docs/cookbook/common-patterns.md#fork-with-a-pack-setting-override`
example must run end-to-end via the CLI.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from activegraph import SQLiteEventStore


REPO_ROOT = Path(__file__).resolve().parents[1]


def _run_cli(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """Invoke the activegraph CLI as a subprocess.

    Tests bind to the CLI surface, not the Python API — this is the
    documentation-vs-implementation gap T3 closes.
    """
    return subprocess.run(
        [sys.executable, "-m", "activegraph"] + args,
        cwd=cwd or REPO_ROOT,
        capture_output=True,
        text=True,
    )


def _seed_run(db_path: Path) -> str:
    """Create a SQLite-backed parent run for fork testing."""
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


# ============================================================================
# CLI surface — `--set` flag exists and parses
# ============================================================================


def test_cli_fork_help_lists_set_flag() -> None:
    """`activegraph fork --help` must list `--set` per docs/reference/cli.md:133."""
    result = _run_cli(["fork", "--help"])
    assert result.returncode == 0, f"--help exit nonzero: {result.stderr}"
    assert "--set" in result.stdout, (
        "fork --help does not list --set; the flag was promised in "
        "docs/reference/cli.md:133 and CONTRACT v1.1 #1"
    )


def test_cli_accepts_set_with_valid_dotted_key_equals_value(tmp_path: Path) -> None:
    """`--set <pack>.<key>=<value>` with valid input → exit 0 + new_run_id."""
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
    assert result.returncode == 0, (
        f"fork --set exit={result.returncode}; stderr={result.stderr}; "
        f"stdout={result.stdout}"
    )
    payload = json.loads(result.stdout)
    assert "new_run_id" in payload
    assert payload.get("overrides", {}).get(
        "diligence.confidence_threshold_for_review"
    ) == 0.9, (
        "Override value not surfaced in --json output; D-3 full-attestation "
        "requires the typed value to be visible post-fork."
    )


def test_cli_rejects_malformed_set_missing_equals(tmp_path: Path) -> None:
    """`--set foo` without `=` fails fast at CLI parse time (D-2 fail-pre-event)."""
    db = tmp_path / "run.db"
    parent_id = _seed_run(db)
    url = f"sqlite:{db}"

    result = _run_cli([
        "fork", url,
        "--run-id", parent_id,
        "--at-event", "evt_001",
        "--set", "diligence_threshold_no_equals",
    ])
    assert result.returncode != 0, (
        "Malformed --set must fail fast per D-2; got exit 0"
    )
    assert "=" in result.stderr or "malformed" in result.stderr.lower(), (
        f"Expected diagnostic about missing '='; got stderr={result.stderr!r}"
    )


def test_cli_rejects_set_without_pack_prefix(tmp_path: Path) -> None:
    """`--set foo=bar` without `<pack>.<key>` form fails per docs/concepts/forking.md."""
    db = tmp_path / "run.db"
    parent_id = _seed_run(db)
    url = f"sqlite:{db}"

    result = _run_cli([
        "fork", url,
        "--run-id", parent_id,
        "--at-event", "evt_001",
        "--set", "foo=bar",
    ])
    assert result.returncode != 0, (
        "Non-dotted --set key must fail; the form is `<pack>.<key>=<value>`"
    )


def test_cli_rejects_set_for_unknown_pack(tmp_path: Path) -> None:
    """`--set unknownpack.k=v` fails per D-2 (validate_override raises InvalidOverrideError)."""
    db = tmp_path / "run.db"
    parent_id = _seed_run(db)
    url = f"sqlite:{db}"

    result = _run_cli([
        "fork", url,
        "--run-id", parent_id,
        "--at-event", "evt_001",
        "--set", "unknownpack.threshold=0.5",
    ])
    assert result.returncode != 0, "Unknown pack must fail at validate_override"
    assert (
        "InvalidOverrideError" in result.stderr
        or "unknown pack" in result.stderr.lower()
        or "unknownpack" in result.stderr.lower()
    ), f"Expected InvalidOverrideError diagnostic; got stderr={result.stderr!r}"


def test_cli_rejects_set_for_unknown_key_within_known_pack(tmp_path: Path) -> None:
    """`--set diligence.nonexistent=0.5` fails per D-2 (key not in settings_schema)."""
    db = tmp_path / "run.db"
    parent_id = _seed_run(db)
    url = f"sqlite:{db}"

    result = _run_cli([
        "fork", url,
        "--run-id", parent_id,
        "--at-event", "evt_001",
        "--set", "diligence.nonexistent_key=0.5",
    ])
    assert result.returncode != 0
    assert (
        "InvalidOverrideError" in result.stderr
        or "nonexistent" in result.stderr.lower()
    ), f"Expected key-not-in-schema diagnostic; got stderr={result.stderr!r}"


def test_cli_rejects_set_when_value_fails_pydantic_coercion(tmp_path: Path) -> None:
    """`--set diligence.confidence_threshold_for_review=not_a_number` fails per D-2+D-4.

    D-4: Pydantic field validator on the float-typed field rejects
    "not_a_number". D-2: validation fires at fork-creation pre-event,
    so no fork.override.applied is minted on failure.
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
    assert result.returncode != 0, "Bad value must fail at validate_override"
    assert (
        "InvalidOverrideError" in result.stderr
        or "not_a_number" in result.stderr
        or "float" in result.stderr.lower()
    ), f"Expected Pydantic coercion failure diagnostic; got stderr={result.stderr!r}"


def test_cli_multiple_set_flags_compose(tmp_path: Path) -> None:
    """Per docs/reference/cli.md:143 — "multiple `--set` flags compose"."""
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
    assert result.returncode == 0, (
        f"Composing --set flags failed: stderr={result.stderr}"
    )
    payload = json.loads(result.stdout)
    overrides = payload.get("overrides", {})
    assert overrides.get("diligence.confidence_threshold_for_review") == 0.85
    assert overrides.get("diligence.support_threshold") == 0.95


# ============================================================================
# D-2 helper surface — validate_override factored for unit testing
# ============================================================================


def test_validate_override_helper_exists_at_documented_location() -> None:
    """D-2 §"helper": `validate_override(key, value, pack) -> CoercedOverride`.

    Importable from activegraph (or a stable submodule); raises
    InvalidOverrideError on failure; returns the typed coerced value
    on success per D-4 §"helper returns CoercedOverride".
    """
    try:
        from activegraph.core.overrides import validate_override  # type: ignore[import-not-found]
    except ImportError:
        try:
            from activegraph.runtime.overrides import validate_override  # type: ignore[import-not-found,no-redef]
        except ImportError as exc:
            pytest.fail(
                f"validate_override helper not importable from "
                f"activegraph.core.overrides or activegraph.runtime.overrides: {exc}"
            )

    assert callable(validate_override)


def test_validate_override_returns_coerced_typed_value() -> None:
    """D-4: helper returns the Pydantic-coerced typed value, not the raw string."""
    pytest.importorskip("activegraph.core.overrides")
    from activegraph.core.overrides import validate_override

    from activegraph.packs.diligence import diligence_pack  # type: ignore[import-not-found]

    coerced = validate_override(
        key="confidence_threshold_for_review",
        value="0.85",
        pack=diligence_pack,
    )
    # D-4: typed return, not raw string
    assert coerced.value == 0.85
    assert isinstance(coerced.value, float)


def test_validate_override_raises_invalid_override_error_on_bad_value() -> None:
    """D-2: helper raises InvalidOverrideError(key, value, schema_constraint)."""
    pytest.importorskip("activegraph.core.overrides")
    from activegraph.core.overrides import validate_override, InvalidOverrideError

    from activegraph.packs.diligence import diligence_pack  # type: ignore[import-not-found]

    with pytest.raises(InvalidOverrideError) as excinfo:
        validate_override(
            key="confidence_threshold_for_review",
            value="not_a_number",
            pack=diligence_pack,
        )
    err = excinfo.value
    assert getattr(err, "key", None) == "confidence_threshold_for_review"
    assert getattr(err, "value", None) == "not_a_number"
