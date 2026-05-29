"""Coverage for activegraph.runtime.budget.Budget.remaining (T7 medium 008).

Target: activegraph.runtime.budget.Budget.remaining — returns True while the
run is under every configured limit, False once any dimension is exceeded, and
records which dimension tripped in `_exhausted_by` (surfaced via exhausted_by()).
Previously uncovered: no test file referenced Budget.remaining directly.

Real Budget fixtures, no mocks of the API under test.
"""

from decimal import Decimal

from activegraph.runtime.budget import Budget


def test_activegraph_runtime_budget_Budget_remaining_true_under_limits() -> None:
    # Happy path: a counter dimension with headroom stays remaining()==True.
    budget = Budget({"max_events": 5})
    assert budget.remaining() is True
    budget.consume("max_events", 4.0)
    assert budget.remaining() is True
    assert budget.exhausted_by() is None


def test_activegraph_runtime_budget_Budget_remaining_no_limits_always_true() -> None:
    # Boundary: with no limits configured every dimension is +inf, so
    # remaining() is True regardless of consumption.
    budget = Budget()
    budget.consume("max_events", 1_000_000.0)
    assert budget.remaining() is True
    assert budget.exhausted_by() is None


def test_activegraph_runtime_budget_Budget_remaining_false_when_counter_exceeded() -> None:
    # Error path: hitting a counter limit flips remaining() to False and records
    # the tripped dimension.
    budget = Budget({"max_events": 2})
    budget.consume("max_events", 2.0)
    assert budget.remaining() is False
    assert budget.exhausted_by() == "max_events"


def test_activegraph_runtime_budget_Budget_remaining_false_when_cost_exceeded() -> None:
    # Error path on the Decimal cost dimension: once cost_used reaches the
    # ceiling, remaining() is False and attributes it to max_cost_usd.
    budget = Budget({"max_cost_usd": Decimal("1.00")})
    assert budget.remaining() is True
    budget.add_cost(Decimal("1.00"))
    assert budget.remaining() is False
    assert budget.exhausted_by() == "max_cost_usd"
