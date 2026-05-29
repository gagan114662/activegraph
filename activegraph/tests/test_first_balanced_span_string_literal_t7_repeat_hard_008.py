r"""T7 repeat HARD 008 — docstring↔code drift in ``_first_balanced_span``.

``activegraph.llm.parsing._first_balanced_span`` documents (parsing.py:38-43):

    Return the first balanced ``{...}`` or ``[...]`` span in ``text``.

    Scans for the first ``{`` or ``[`` and returns the substring up to its
    matching close bracket, tracking nesting and *ignoring brackets that
    appear inside JSON string literals (with escape handling)*. Returns
    ``None`` when no opening bracket exists or it never closes.

The bug: only the *balance-counting* loop respects string-literal context.
The *start-finding* loop (the first ``for i, ch in enumerate(text)`` that
locates the opening bracket) scans byte-by-byte with NO string tracking. So
when a ``{`` or ``[`` appears inside a quoted string that precedes the real
JSON, that in-string bracket is chosen as the span start. Balance counting
then begins inside the string, the real balanced object after it is never
reached, and the function returns ``None`` (or a malformed span) — directly
contradicting the docstring's promise to *ignore brackets inside string
literals* and recover the *first balanced* span.

These tests assert the DOCUMENTED behavior: a bracket inside a leading string
literal is ignored, and the first genuinely-balanced JSON span is recovered.
"""

from __future__ import annotations

from activegraph.llm.parsing import _first_balanced_span


def test_open_bracket_inside_leading_string_literal_is_ignored() -> None:
    # A '[' appears inside a quoted string BEFORE the real object. The
    # docstring says brackets inside string literals are ignored, so the
    # first *balanced* span is the {...} object that follows.
    text = 'prefix "[" then {"a": 1} end'
    assert _first_balanced_span(text) == '{"a": 1}'


def test_open_brace_inside_leading_string_literal_is_ignored() -> None:
    # A '{' inside a quoted string must not be taken as the span start.
    text = 'say "{not json" then {"a": 1}'
    assert _first_balanced_span(text) == '{"a": 1}'


def test_plain_object_still_recovered() -> None:
    # Sanity: the simple case the fix must not regress.
    assert _first_balanced_span('{"a": 1}') == '{"a": 1}'


def test_genuinely_no_bracket_still_returns_none() -> None:
    # Sanity: a bracket that only ever appears inside a string (no real JSON)
    # has no balanced span, so None is still correct.
    assert _first_balanced_span('just "{" prose, no real json') is None
