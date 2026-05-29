"""T7 HARD repeat 003 — docstring↔code drift regression test.

`Runtime.status()` (activegraph/runtime/runtime.py) and the
`RuntimeStatus` module docstring (activegraph/observability/status.py)
both promise the snapshot is IMMUTABLE:

    "Returns immutable data; mutating any field raises."   (runtime.py:1689)
    "... returns immutable data."                          (status.py:5)

The top-level `RuntimeStatus` dataclass is frozen, so assigning a
top-level field raises `FrozenInstanceError`. But the nested
`BudgetSnapshot.used` / `.limits` are plain `dict`s — mutating them
succeeds SILENTLY, so the returned snapshot is NOT actually immutable.
That gap (documented-immutable vs actually-mutable) is the bug.

These tests assert the DOCUMENTED behavior: mutating any field of the
snapshot — including the nested budget dicts — must raise.
"""

from __future__ import annotations

import dataclasses

import pytest

from activegraph.observability.status import BudgetSnapshot, RuntimeStatus


def _make_snapshot() -> RuntimeStatus:
    budget = BudgetSnapshot(
        used={"calls": 1.0},
        limits={"calls": 10.0},
        cost_used_usd="0",
        cost_limit_usd=None,
        exhausted_by=None,
    )
    return RuntimeStatus(
        run_id="run-1",
        state="idle",
        queue_depth=0,
        events_processed=1,
        budget=budget,
        frame=None,
        registered_behaviors=(),
        recent_events=(),
    )


def test_toplevel_field_assignment_raises() -> None:
    """The documented frozen-snapshot guarantee for top-level fields."""
    status = _make_snapshot()
    with pytest.raises(dataclasses.FrozenInstanceError):
        status.run_id = "mutated"  # type: ignore[misc]


def test_budget_used_is_not_mutable() -> None:
    """Docstring: 'mutating any field raises'. The nested `budget.used`
    dict must therefore reject mutation rather than silently accept it.
    """
    status = _make_snapshot()
    with pytest.raises((TypeError, dataclasses.FrozenInstanceError)):
        status.budget.used["calls"] = 999.0  # type: ignore[index]


def test_budget_limits_is_not_mutable() -> None:
    """Same guarantee for the nested `budget.limits` dict."""
    status = _make_snapshot()
    with pytest.raises((TypeError, dataclasses.FrozenInstanceError)):
        status.budget.limits["calls"] = 0.0  # type: ignore[index]
