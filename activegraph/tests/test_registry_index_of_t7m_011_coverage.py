"""T7 medium 011 coverage for activegraph.runtime.registry.Registry.index_of.

Targets the previously-uncovered public API ``Registry.index_of`` with real
``Behavior`` fixtures (no mocks of the API under test). ``index_of`` returns the
registration index of a behavior by identity, or ``-1`` when the behavior is not
registered. Tests exercise the happy path (registered behaviors resolve to their
positional index in registration order, per CONTRACT #10) and the boundary path
(an unregistered behavior, and identity-not-equality semantics).
"""

from __future__ import annotations

from activegraph.behaviors.base import Behavior
from activegraph.runtime.registry import Registry


def _noop(event, graph, ctx) -> None:  # real callable; not a mock of the API
    return None


def _behavior(name: str) -> Behavior:
    """Build a real Behavior fixture (the Registry is the API under test)."""
    return Behavior(name=name, fn=_noop, on=["thing.created"])


def test_activegraph_runtime_registry_Registry_index_of_returns_registration_order():
    """Happy path: each registered behavior resolves to its registration index."""
    first = _behavior("first")
    second = _behavior("second")
    third = _behavior("third")
    registry = Registry([first, second, third])

    assert registry.index_of(first) == 0
    assert registry.index_of(second) == 1
    assert registry.index_of(third) == 2
    # Sanity: the index round-trips against the public all() ordering.
    assert registry.all()[registry.index_of(second)] is second


def test_activegraph_runtime_registry_Registry_index_of_returns_minus_one_when_absent():
    """Boundary: an unregistered behavior yields -1, not an exception."""
    registered = _behavior("registered")
    registry = Registry([registered])

    stranger = _behavior("stranger")
    assert registry.index_of(stranger) == -1
    # Empty registry: any lookup is absent.
    assert Registry([]).index_of(registered) == -1


def test_activegraph_runtime_registry_Registry_index_of_uses_identity_not_equality():
    """Boundary: lookup is by object identity (``is``), not value equality.

    Two distinct Behavior instances with identical fields must not collide;
    only the exact registered object resolves to its index.
    """
    a = _behavior("dup")
    b = _behavior("dup")  # same name + fn, different object
    registry = Registry([a, b])

    assert registry.index_of(a) == 0
    assert registry.index_of(b) == 1
    # A third look-alike that was never registered is absent.
    c = _behavior("dup")
    assert registry.index_of(c) == -1
