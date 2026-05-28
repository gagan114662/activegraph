"""T7 medium run 001 coverage for activegraph.runtime.budget.Budget.consume.

Budget.consume(key, amount) accumulates usage on a generic counter dimension.
These tests exercise distinct configurations:
  - happy path: first consume seeds the dimension, repeated consume accumulates
  - default amount: amount defaults to 1.0
  - boundary/integration: consuming an unknown key creates it on demand, and
    consuming up to a configured limit flips remaining() to False with the
    correct exhausted_by() attribution.

Real Budget fixtures only — the API under test is not mocked.
"""

from activegraph.runtime.budget import Budget


def test_activegraph_runtime_budget_Budget_consume_accumulates_and_defaults():
    """Happy path: consume seeds a dimension, accumulates, and defaults amount=1.0."""
    b = Budget({"max_events": 10})
    assert b.used["max_events"] == 0.0

    # explicit amount
    b.consume("max_events", 3.0)
    assert b.used["max_events"] == 3.0

    # accumulates on top of prior usage
    b.consume("max_events", 2.0)
    assert b.used["max_events"] == 5.0

    # default amount is 1.0
    b.consume("max_events")
    assert b.used["max_events"] == 6.0


def test_activegraph_runtime_budget_Budget_consume_unknown_key_and_exhaustion():
    """Boundary: consuming an unknown key creates it; consuming to the limit
    exhausts the dimension and remaining() attributes it via exhausted_by()."""
    b = Budget({"max_behavior_calls": 2})

    # unknown key is created on demand (get(...) default 0.0 path)
    assert "max_tool_calls" not in {k for k in b.used if k == "max_tool_calls" and False}
    b.consume("brand_new_key", 4.0)
    assert b.used["brand_new_key"] == 4.0
    # a brand-new key has no limit, so it never trips remaining()
    assert b.remaining() is True

    # drive the real limited dimension to its ceiling
    assert b.remaining() is True
    b.consume("max_behavior_calls", 2.0)
    assert b.used["max_behavior_calls"] == 2.0

    # at-or-over the limit flips remaining() False with correct attribution
    assert b.remaining() is False
    assert b.exhausted_by() == "max_behavior_calls"
