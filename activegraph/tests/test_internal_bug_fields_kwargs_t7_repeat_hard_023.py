"""T7 repeat-hard 023 — docstring↔code drift in `internal_bug_fields`.

`activegraph/errors.py::internal_bug_fields` documents (line ~300):

    "Returns the kwargs dict that an :class:`ActiveGraphError` subclass's
     structured ``__init__`` consumes."

That is a falsifiable behavioral promise: the returned mapping should be
directly splattable as ``**fields`` into ``ActiveGraphError(**fields)``
(or any structured subclass). The code violates it: it emits the key
``summary`` while ``ActiveGraphError.__init__`` takes the one-line message
as the parameter ``summary_or_message`` (``summary`` is not a valid kwarg).
So ``ActiveGraphError(**fields)`` raises
``TypeError: ... unexpected keyword argument 'summary'`` — exactly the
"kwargs dict the __init__ consumes" the docstring promised it would be.

These tests assert the DOCUMENTED behavior and FAIL against the current
code (the bug), then PASS after the fix.
"""

from __future__ import annotations

import pytest

from activegraph.errors import (
    ActiveGraphError,
    ExecutionError,
    internal_bug_fields,
)


def _sample_fields() -> dict:
    return internal_bug_fields(
        summary="boom",
        what_happened="the evaluator saw an operator it does not handle",
        why_invariant="the operator table is the source of truth",
        location="activegraph/runtime/patterns.py:_eval_where",
        extra_context={"operator": "~="},
    )


def test_fields_splat_directly_into_active_graph_error():
    """The documented contract: the returned dict IS the kwargs an
    ActiveGraphError structured __init__ consumes — so ``**fields`` works."""
    fields = _sample_fields()
    err = ActiveGraphError(**fields)  # must not raise TypeError
    # The one-line summary must survive into the rendered message.
    assert "boom" in str(err)


def test_fields_splat_into_structured_subclass():
    """Same contract for a concrete subclass (the real call-site shape)."""
    fields = _sample_fields()
    err = ExecutionError(**fields)
    rendered = str(err)
    assert "boom" in rendered
    assert "What failed:" in rendered
    assert "the evaluator saw an operator it does not handle" in rendered


def test_structured_fields_are_preserved_through_splat():
    """The why / how_to_fix / context the helper builds must reach the
    error unchanged when splatted, proving the dict is truly consumable."""
    fields = _sample_fields()
    err = ExecutionError(**fields)
    assert err.why.startswith("the operator table is the source of truth")
    assert "framework bug" in err.how_to_fix
    assert err.context.get("internal") is True
    assert err.context.get("operator") == "~="
    assert err.context.get("internal_error_location") == (
        "activegraph/runtime/patterns.py:_eval_where"
    )
