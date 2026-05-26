from decimal import Decimal

import pytest

from activegraph.runtime.budget import Budget


pytestmark = getattr(pytest.mark, "activegraph.runtime.budget.Budget.snapshot")


def test_activegraph_runtime_budget_budget_snapshot_serializes_finite_limits() -> None:
    budget = Budget({"max_events": 3, "max_cost_usd": "0.25"})
    budget.consume("max_events", 2)
    budget.add_cost(Decimal("0.10"))

    snapshot = budget.snapshot()

    assert snapshot["used"]["max_events"] == 2.0
    assert snapshot["used"]["max_cost_usd"] == 0.1
    assert snapshot["limits"]["max_events"] == 3.0
    assert snapshot["limits"]["max_cost_usd"] == 0.25
    assert snapshot["cost_used_usd"] == "0.10"
    assert snapshot["cost_limit_usd"] == "0.25"


def test_activegraph_runtime_budget_budget_snapshot_marks_missing_limits_as_none() -> None:
    budget = Budget()
    budget.consume("custom_counter", 4)

    snapshot = budget.snapshot()

    assert snapshot["used"]["custom_counter"] == 4.0
    assert snapshot["limits"]["max_events"] is None
    assert snapshot["limits"]["max_cost_usd"] is None
    assert snapshot["cost_used_usd"] == "0"
    assert snapshot["cost_limit_usd"] is None
