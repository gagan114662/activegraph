from activegraph import FrozenClock, TickingClock


def test_frozen_clock_returns_same_value():
    c = FrozenClock("2026-05-15T10:32:01Z")
    assert c.now() == "2026-05-15T10:32:01Z"
    assert c.now() == "2026-05-15T10:32:01Z"


def test_ticking_clock_advances():
    c = TickingClock("2026-05-15T10:32:01Z", step_seconds=1)
    a, b, d = c.now(), c.now(), c.now()
    assert a == "2026-05-15T10:32:01Z"
    assert b == "2026-05-15T10:32:02Z"
    assert d == "2026-05-15T10:32:03Z"
