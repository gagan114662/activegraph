"""T7 repeat-hard 009 — docstring↔code drift regression.

`canonicalize_args` (activegraph/tools/cache.py) documents itself as
normalizing tool args "into a JSON-stable shape for hashing" and
explicitly promises:

    - sort_keys at JSON-dump time guarantees ordering stability.

i.e. the returned normalized shape is meant to be order-stable: two
arg dicts that differ ONLY in key insertion order must canonicalize to
the same shape. The function recurses dicts while preserving insertion
order and never sorts, so its output is NOT order-stable — the
"ordering stability" the docstring guarantees does not hold for the
function's own return value. (The downstream `hash_tool_call` sorts at
dump time, masking the gap for the hash, but `canonicalize_args` is a
public helper whose output is also persisted verbatim into recorded
tool fixtures.)

This test asserts the DOCUMENTED behavior and fails against the
pre-fix code.
"""

from activegraph.tools.cache import canonicalize_args


def _ordered(d):
    """Recursively render a dict as nested (key, value) item lists so the
    comparison is sensitive to key ORDER, not just key/value membership."""
    if isinstance(d, dict):
        return [(k, _ordered(v)) for k, v in d.items()]
    if isinstance(d, list):
        return [_ordered(v) for v in d]
    return d


def test_canonicalize_args_is_order_stable_for_equal_dicts():
    # Same semantic args, different key insertion order — top level + nested.
    a = {"beta": 1, "alpha": {"y": 2, "x": 3}}
    b = {"alpha": {"x": 3, "y": 2}, "beta": 1}

    ca = canonicalize_args(a)
    cb = canonicalize_args(b)

    # The docstring promises ordering stability: the normalized shapes
    # must be order-identical, not merely equal-as-unordered-dicts.
    assert _ordered(ca) == _ordered(cb), (
        "canonicalize_args output is not order-stable: "
        f"{_ordered(ca)!r} != {_ordered(cb)!r}"
    )


def test_canonicalize_args_emits_sorted_keys():
    # Ordering stability, concretely: keys come out sorted at every level.
    out = canonicalize_args({"c": 1, "a": {"z": 0, "m": 0}, "b": 2})
    assert list(out.keys()) == sorted(out.keys())
    assert list(out["a"].keys()) == sorted(out["a"].keys())
