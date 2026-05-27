from decimal import Decimal

import pytest

from activegraph.runtime.budget import Budget


pytestmark = getattr(pytest.mark, "activegraph.runtime.budget.Budget.add_cost")


def test_activegraph_runtime_budget_budget_add_cost_accumulates_decimal_amounts_without_float_drift() -> None:
    budget = Budget({"max_cost_usd": "1.00"})

    for _ in range(1000):
        budget.add_cost(Decimal("0.0001"))

    assert budget.cost_used == Decimal("0.1000")
    assert budget.used["max_cost_usd"] == pytest.approx(0.1)


def test_activegraph_runtime_budget_budget_add_cost_coerces_non_decimal_amounts_through_as_decimal() -> None:
    budget = Budget({"max_cost_usd": "5.00"})

    budget.add_cost(Decimal("0.25"))
    budget.add_cost(0.10)
    budget.add_cost("0.05")
    budget.add_cost(1)

    assert budget.cost_used == Decimal("1.40")
    assert isinstance(budget.cost_used, Decimal)
    assert budget.used["max_cost_usd"] == pytest.approx(1.40)


def test_activegraph_runtime_budget_budget_add_cost_works_without_cost_limit_and_does_not_set_exhausted_by() -> None:
    budget = Budget()

    budget.add_cost(Decimal("3.14"))

    assert budget.has_cost_limit() is False
    assert budget.cost_used == Decimal("3.14")
    assert budget.used["max_cost_usd"] == pytest.approx(3.14)
    assert budget.remaining() is True
    assert budget.exhausted_by() is None
