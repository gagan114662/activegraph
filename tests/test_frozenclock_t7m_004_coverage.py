"""T7 medium 004 coverage for activegraph.core.clock.FrozenClock.

FrozenClock is used elsewhere as a test fixture, but no test file directly
exercises its own contract: that it returns a stable, configurable timestamp
and honors the Clock interface. These tests cover that gap with real objects
(no mocks of the API under test).
"""

from __future__ import annotations

from activegraph.core.clock import Clock, FrozenClock


def test_FrozenClock_default_timestamp_is_stable_across_calls() -> None:
    """Happy path: the default FrozenClock returns its documented default and
    never advances, no matter how many times now() is called."""
    clock = FrozenClock()

    first = clock.now()
    second = clock.now()
    third = clock.now()

    assert first == "2026-05-15T10:32:01Z"
    assert first == second == third
    # It is a real Clock, not just a duck-typed stand-in.
    assert isinstance(clock, Clock)


def test_FrozenClock_custom_timestamp_is_returned_verbatim() -> None:
    """Boundary/config path: a caller-supplied timestamp is echoed back exactly,
    and distinct instances stay independent of one another."""
    custom = "1999-12-31T23:59:59Z"
    clock = FrozenClock(t=custom)

    assert clock.now() == custom
    # Repeated reads remain frozen at the configured value.
    assert clock.now() == custom

    # A second instance with a different value does not leak state.
    other = FrozenClock(t="2000-01-01T00:00:00Z")
    assert other.now() == "2000-01-01T00:00:00Z"
    assert clock.now() == custom
