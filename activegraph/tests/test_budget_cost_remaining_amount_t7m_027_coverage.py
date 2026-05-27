from decimal import Decimal

import pytest

from activegraph.runtime.budget import Budget


pytestmark = getattr(pytest.mark, "activegraph.runtime.budget.Budget.cost_remaining_amount")


def test_activegraph_runtime_budget_budget_cost_remaining_amount_returns_none_without_limit() -> None:
    budget = Budget({"max_events": 5})

    assert budget.cost_remaining_amount() is None


def test_activegraph_runtime_budget_budget_cost_remaining_amount_reports_unspent_balance() -> None:
    budget = Budget({"max_cost_usd": "0.50"})
    budget.add_cost(Decimal("0.20"))

    remaining = budget.cost_remaining_amount()

    assert isinstance(remaining, Decimal)
    assert remaining == Decimal("0.30")


def test_activegraph_runtime_budget_budget_cost_remaining_amount_clamps_to_zero_when_exhausted() -> None:
    budget = Budget({"max_cost_usd": "0.10"})
    budget.add_cost(Decimal("0.25"))

    remaining = budget.cost_remaining_amount()

    assert isinstance(remaining, Decimal)
    assert remaining == Decimal("0")
