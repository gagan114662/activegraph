from decimal import Decimal

import pytest

from activegraph.runtime.budget import Budget


pytestmark = getattr(pytest.mark, "activegraph.runtime.budget.Budget.exhausted_by")


def test_activegraph_runtime_budget_budget_exhausted_by_returns_none_on_fresh_budget() -> None:
    budget = Budget({"max_events": 5, "max_cost_usd": "1.00"})

    assert budget.exhausted_by() is None


def test_activegraph_runtime_budget_budget_exhausted_by_reports_counter_dimension_after_remaining_trips() -> None:
    budget = Budget({"max_events": 2})

    budget.consume("max_events", 2.0)
    assert budget.remaining() is False

    assert budget.exhausted_by() == "max_events"


def test_activegraph_runtime_budget_budget_exhausted_by_reports_cost_dimension_when_cost_limit_hit() -> None:
    budget = Budget({"max_cost_usd": "0.10"})

    budget.add_cost(Decimal("0.10"))
    assert budget.remaining() is False

    assert budget.exhausted_by() == "max_cost_usd"
