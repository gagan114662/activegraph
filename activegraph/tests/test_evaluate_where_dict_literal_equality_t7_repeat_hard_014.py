"""T7 repeat hard 014 — docstring↔code drift regression for evaluate_where.

``activegraph.core.graph.evaluate_where`` documents (in its docstring):

    "Keys are dotted paths. Values are either literals (equality) or
     ``{"op": value}`` dicts for comparisons."

So a value may be EITHER a literal (matched by equality) OR an operator
dict like ``{">": 5}``. The implementation, however, treats EVERY dict
value as an operator dict:

    if isinstance(expected, dict):
        for op, value in expected.items():
            fn = _OPS.get(op)
            ...

A literal value that happens to be a *dict* (the documented "literals
(equality)" case for dict-shaped data — e.g. ``where={"meta": {"k": 1}}``)
never reaches the equality branch. Each key of the literal dict is looked
up in ``_OPS``, misses, and the evaluator RAISES
``InternalEvaluatorError("unknown where operator: 'k'")`` — turning a
legitimate equality filter into an internal-bug crash.

This is a real bug: objects routinely carry dict-valued ``data`` fields,
and ``Graph.objects(where=...)`` / ``View.objects(where=...)`` are the
public query API. Filtering an object by a nested-dict field value is
exactly the documented "literals (equality)" path, and it explodes.

These tests assert the DOCUMENTED behavior: a dict literal whose keys are
NOT operators is matched by equality (True when equal, False when not),
while a genuine operator dict (``{">": ...}``) still does comparison.
"""
from __future__ import annotations

import pytest

from activegraph.core.graph import evaluate_where


def test_dict_literal_value_matches_by_equality():
    # Documented: a literal value (here a dict) is matched by EQUALITY.
    root = {"meta": {"k": 1}}
    # Equal nested dict -> True.
    assert evaluate_where({"meta": {"k": 1}}, root) is True


def test_dict_literal_value_unequal_is_false():
    root = {"meta": {"k": 1}}
    # Different nested dict -> False (NOT an exception).
    assert evaluate_where({"meta": {"k": 2}}, root) is False


def test_operator_dict_still_does_comparison():
    # A genuine operator dict must keep working as a comparison.
    root = {"score": 10}
    assert evaluate_where({"score": {">": 5}}, root) is True
    assert evaluate_where({"score": {">": 50}}, root) is False
