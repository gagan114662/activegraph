"""T7 medium run 014 coverage for activegraph.runtime.registry.Registry.all.

Exercises the documented contract surface of ``Registry.all`` with real
``Behavior`` and ``Registry`` fixtures (no mocks of the API under test):

- happy path: returns every registered behavior in registration order,
- boundary: an empty registry returns an empty list,
- defensive-copy semantics: ``all()`` returns a fresh list, so mutating the
  returned value must not corrupt the registry's internal state.

Test names embed ``registry_all`` so ``pytest -k registry_all`` collects them.
"""

from __future__ import annotations

from activegraph.behaviors.base import Behavior
from activegraph.runtime.registry import Registry


def _noop(event, graph, ctx):  # pragma: no cover - never invoked by all()
    return None


def test_registry_all_returns_registered_behaviors_in_order():
    """Happy path: ``all()`` returns exactly the registered behaviors,
    preserving registration order."""
    first = Behavior(name="first", fn=_noop, on=["thing.created"])
    second = Behavior(name="second", fn=_noop, on=["thing.updated"])
    third = Behavior(name="third", fn=_noop, on=["thing.deleted"])

    registry = Registry([first, second, third])

    result = registry.all()

    assert result == [first, second, third]
    assert [b.name for b in result] == ["first", "second", "third"]


def test_registry_all_on_empty_registry_returns_empty_list():
    """Boundary: an empty registry yields an empty list, not None."""
    registry = Registry([])

    result = registry.all()

    assert result == []
    assert isinstance(result, list)


def test_registry_all_returns_defensive_copy_not_internal_list():
    """Mutating the list returned by ``all()`` must not change what the
    registry reports on a subsequent call -- it returns a fresh copy."""
    only = Behavior(name="only", fn=_noop, on=["thing.created"])
    registry = Registry([only])

    first_call = registry.all()
    first_call.clear()  # mutate the returned list

    second_call = registry.all()

    # The registry is unaffected by mutation of a prior return value.
    assert second_call == [only]
    assert first_call is not second_call
