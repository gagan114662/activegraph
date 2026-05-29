"""T7 HARD repetition run 005 — docstring↔code drift regression test.

Drift target: ``activegraph.core.clock.TickingClock``.

The class docstring (activegraph/core/clock.py:40) documents:

    "Monotonically advances by `step` seconds on every call."

"Monotonically advances" is a hard invariant: successive ``now()`` calls
must be strictly non-decreasing (and for a *ticking* clock, increasing).
The constructor, however, accepts ``step_seconds`` with no validation, so a
caller can construct a clock that moves *backward* (negative step) or stalls
(zero step) — both of which violate the documented monotonicity. A clock
documented to advance monotonically must not be constructible in a state
where it cannot honor that contract.

This test asserts the DOCUMENTED behavior and FAILS against the current code,
which silently accepts a non-monotonic step.
"""

import pytest

from activegraph.core.clock import TickingClock

# Mirror the verifier's symbol-resolution form (it matches the underscored
# dotted symbol against test names).
pytestmark = getattr(pytest.mark, "activegraph.core.clock.TickingClock", pytest.mark.unit)


def test_ticking_clock_rejects_negative_step_to_preserve_monotonicity():
    """A negative step would make now() go backward, violating the documented
    'Monotonically advances' invariant — the constructor must refuse it."""
    with pytest.raises(ValueError):
        TickingClock(step_seconds=-1)


def test_ticking_clock_rejects_zero_step_to_preserve_monotonicity():
    """A zero step would stall the clock (no advance), violating 'advances ...
    on every call' — the constructor must refuse it."""
    with pytest.raises(ValueError):
        TickingClock(step_seconds=0)


def test_ticking_clock_is_actually_monotonic_when_constructible():
    """When a TickingClock is constructible, successive now() calls must be
    strictly increasing, matching the documented monotonic contract."""
    clock = TickingClock(step_seconds=1)
    stamps = [clock.now() for _ in range(5)]
    assert stamps == sorted(stamps), f"timestamps not monotonic: {stamps}"
    assert len(set(stamps)) == len(stamps), f"timestamps not strictly increasing: {stamps}"
