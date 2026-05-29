"""T7 medium run 019 coverage for activegraph.runtime.patterns.Match.get.

Target symbol: activegraph.runtime.patterns.Match.get

Match.get returns a binding by key, or a fallback when the key is absent.
This is the safe-lookup counterpart to Match.__getitem__ (which raises on
a missing key). The tests below exercise the real Match dataclass with real
binding dicts (no mocks of the API under test) across distinct configurations:
happy path (key present), boundary (key absent with explicit default),
implicit-None default, and the KeyError contrast against __getitem__.
"""

import pytest

from activegraph.runtime.patterns import Match


def test_activegraph_runtime_patterns_Match_get_returns_bound_value_happy_path():
    """Happy path: get returns the bound id when the key is present."""
    match = Match(bindings={"claim": "obj_1", "supports": "rel_7"})

    assert match.get("claim") == "obj_1"
    assert match.get("supports") == "rel_7"
    # An explicit default is ignored when the key is bound.
    assert match.get("claim", "fallback") == "obj_1"


def test_activegraph_runtime_patterns_Match_get_returns_default_when_absent():
    """Boundary: get returns the supplied default for an unbound variable."""
    match = Match(bindings={"claim": "obj_1"})

    # Unbound variable (e.g. an anonymous node) yields the explicit default.
    assert match.get("missing", "default_value") == "default_value"
    # Implicit default is None when no fallback is supplied.
    assert match.get("missing") is None
    # Falsy-but-explicit defaults are returned as-is (not coerced to None).
    assert match.get("missing", "") == ""


def test_activegraph_runtime_patterns_Match_get_does_not_mutate_bindings():
    """get is a pure read: a missing-key lookup must not insert the key."""
    match = Match(bindings={"claim": "obj_1"})

    match.get("missing", "default_value")

    assert "missing" not in match.bindings
    assert match.bindings == {"claim": "obj_1"}


def test_activegraph_runtime_patterns_Match_get_contrasts_with_getitem_raising():
    """Error contrast: __getitem__ raises KeyError where get returns a default."""
    match = Match(bindings={"claim": "obj_1"})

    # get is the safe form: no exception, returns the fallback.
    assert match.get("absent", "safe") == "safe"

    # __getitem__ is the strict form: raises on the same missing key.
    with pytest.raises(KeyError):
        _ = match["absent"]
