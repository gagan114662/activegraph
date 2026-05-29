"""T7 medium repetition run 015 — coverage for ``Budget.start``.

Target: ``activegraph.runtime.budget.Budget.start`` — previously exercised by
no test (no test calls ``.start()`` on a Budget). ``start`` records a monotonic
baseline used exclusively by the ``max_seconds`` dimension of ``remaining()``:
until ``start`` is called, ``_start`` is ``None`` and the time dimension is
skipped, so the budget can never be reported as time-exhausted. Calling
``start`` is what "arms the clock".

These tests use real ``Budget`` instances and the real ``remaining`` /
``exhausted_by`` machinery — nothing about the API under test is mocked.
"""

from __future__ import annotations

from activegraph.runtime.budget import Budget


def test_budget_start_arms_the_clock_and_remaining_holds_under_generous_limit() -> None:
    """Happy path: with a generous ``max_seconds`` limit, calling ``start``
    records a baseline and ``remaining()`` stays True (not yet exhausted)."""
    budget = Budget({"max_seconds": 3600})

    # Before start, the time dimension is disarmed.
    assert budget._start is None

    budget.start()

    # start() records a real monotonic baseline.
    assert budget._start is not None
    # A 1-hour ceiling is nowhere near elapsed, so the run still has budget.
    assert budget.remaining() is True
    assert budget.exhausted_by() is None


def test_budget_start_required_for_max_seconds_exhaustion_boundary() -> None:
    """Boundary/contrast: a ``max_seconds=0`` limit only reports time
    exhaustion AFTER ``start`` arms the clock. Without start, the time
    dimension is skipped and the budget reads as remaining."""
    # Disarmed: max_seconds=0 but start never called -> time dimension skipped.
    disarmed = Budget({"max_seconds": 0})
    assert disarmed.remaining() is True
    assert disarmed.exhausted_by() is None

    # Armed: identical limit, but start() makes the clock live. With a 0-second
    # ceiling, any elapsed monotonic time (>= 0) trips the limit immediately.
    armed = Budget({"max_seconds": 0})
    armed.start()
    assert armed.remaining() is False
    assert armed.exhausted_by() == "max_seconds"
