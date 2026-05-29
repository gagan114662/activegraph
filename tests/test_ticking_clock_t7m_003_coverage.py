"""T7 medium 003 coverage for activegraph.core.clock.TickingClock.

Exercises the monotonic ISO-8601 clock used by tests that care about event
ordering without wall-clock noise. Uses the real TickingClock (no mocks of the
API under test), covering the happy path, the configurable step, and the
boundary contract that the first call returns the start instant before the
clock advances.
"""

from __future__ import annotations

from datetime import datetime, timezone

from activegraph.core.clock import Clock, TickingClock


def test_TickingClock_advances_by_default_step_seconds() -> None:
    """Happy path: each now() advances by the default 1-second step and the
    timestamps come back in ISO-8601 UTC form with a Z suffix."""
    clock = TickingClock(start="2026-05-15T10:32:01Z")

    first = clock.now()
    second = clock.now()
    third = clock.now()

    assert first == "2026-05-15T10:32:01Z"
    assert second == "2026-05-15T10:32:02Z"
    assert third == "2026-05-15T10:32:03Z"

    # Each rendered timestamp is a valid ISO-8601 UTC instant ending in Z.
    for stamp in (first, second, third):
        assert stamp.endswith("Z")
        parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        assert parsed.tzinfo == timezone.utc

    # Strictly monotonic ordering, which is the whole point of the clock.
    assert first < second < third


def test_TickingClock_honors_custom_step_and_subclasses_clock() -> None:
    """Boundary/config behavior: a custom multi-second step is applied AFTER
    the start instant is returned, so the first call still yields `start`.
    Also confirms TickingClock is a Clock and exposes the now() contract."""
    step = 30
    clock = TickingClock(start="2026-12-31T23:59:00Z", step_seconds=step)

    # TickingClock must be usable anywhere a Clock is expected.
    assert isinstance(clock, Clock)

    first = clock.now()
    second = clock.now()
    third = clock.now()

    # First call returns the start instant unchanged (advance happens after).
    assert first == "2026-12-31T23:59:00Z"
    assert second == "2026-12-31T23:59:30Z"
    # Crossing the minute boundary with the configured step.
    assert third == "2027-01-01T00:00:00Z"

    # The delta between consecutive stamps equals the configured step.
    t_first = datetime.fromisoformat(first.replace("Z", "+00:00"))
    t_second = datetime.fromisoformat(second.replace("Z", "+00:00"))
    assert (t_second - t_first).total_seconds() == step
