"""T7 medium 002 coverage for activegraph.runtime.budget.Budget.has_cost_limit.

`Budget.has_cost_limit()` reports whether a `max_cost_usd` ceiling was
configured. Prior to this run no test in the suite exercised it directly
(verified via `pytest --collect-only -k has_cost_limit` -> 0 collected).

These tests construct real Budget instances — no mocks of the API under test.
"""

from decimal import Decimal

from activegraph.runtime.budget import Budget


def test_has_cost_limit_true_when_max_cost_usd_configured():
    """Happy path: a positive max_cost_usd limit means has_cost_limit() is True."""
    budget = Budget(limits={"max_cost_usd": 5.0})
    assert budget.has_cost_limit() is True
    # The configured ceiling is tracked as a Decimal internally.
    assert budget.cost_limit == Decimal("5")


def test_has_cost_limit_false_when_no_limits_supplied():
    """Boundary: a Budget with no limits dict has no cost ceiling."""
    budget = Budget()
    assert budget.has_cost_limit() is False
    assert budget.cost_limit is None


def test_has_cost_limit_false_when_max_cost_usd_is_explicit_none():
    """Edge case: explicitly passing max_cost_usd=None leaves no ceiling."""
    budget = Budget(limits={"max_cost_usd": None})
    assert budget.has_cost_limit() is False
    assert budget.cost_limit is None


def test_has_cost_limit_false_when_only_other_dimensions_limited():
    """Edge case: limiting a non-cost dimension does not create a cost ceiling."""
    budget = Budget(limits={"max_events": 100, "max_seconds": 30})
    assert budget.has_cost_limit() is False
    # Stays False even after recording cost usage, since no ceiling was set.
    budget.add_cost(Decimal("1.50"))
    assert budget.has_cost_limit() is False
