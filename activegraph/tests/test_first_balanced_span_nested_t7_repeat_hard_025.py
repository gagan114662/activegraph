"""T7 repeat-hard 025 — docstring↔code drift on `_first_balanced_span`.

`activegraph/llm/parsing.py:_first_balanced_span` documents (line 38):

    "Return the first balanced ``{...}`` or ``[...]`` span in ``text``."

and (line 41) "tracking nesting".

The matcher loop only tracks depth for the SAME bracket type as the opener.
When the opener is ``{`` and the content contains an inner ``[`` that never
closes, the first ``}`` drops the (outer-only) depth to 0 and the function
returns a span that is NOT balanced — the inner ``[`` has no matching ``]``.

This test asserts the DOCUMENTED behavior: a returned span must be a truly
balanced bracket span (all opened ``{``/``[`` are matched). It FAILS against
the current code, which returns an unbalanced span.
"""

from __future__ import annotations

import json

from activegraph.llm.parsing import _first_balanced_span


def _is_balanced(span: str) -> bool:
    """True iff every ``{``/``[`` in the span (outside string literals) has a
    matching close in the correct order — i.e. the span is a balanced bracket
    span as the docstring promises."""
    stack: list[str] = []
    pairs = {"}": "{", "]": "["}
    in_str = False
    escaped = False
    for ch in span:
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in ("{", "["):
            stack.append(ch)
        elif ch in ("}", "]"):
            if not stack or stack[-1] != pairs[ch]:
                return False
            stack.pop()
    return not stack


def test_first_balanced_span_rejects_unclosed_inner_bracket() -> None:
    # Opener is `{`; the inner `[` is never closed. The docstring promises a
    # *balanced* span, so the function must NOT return `{"a": [1, 2}` (which
    # leaves the `[` dangling). It should keep scanning for a truly balanced
    # span and, finding none, return None.
    text = '{"a": [1, 2}'
    span = _first_balanced_span(text)
    assert span is None or _is_balanced(span), (
        f"docstring promises a BALANCED span, but got unbalanced {span!r} "
        f"(inner '[' has no matching ']')"
    )


def test_first_balanced_span_returns_balanced_for_mixed_nesting() -> None:
    # When a balanced span DOES exist with mixed `{`/`[` nesting, it must be
    # returned intact and be parseable as JSON.
    text = 'noise {"a": [1, 2], "b": {"c": 3}} trailing }'
    span = _first_balanced_span(text)
    assert span is not None, "expected to recover the balanced JSON object"
    assert _is_balanced(span), f"returned span is not balanced: {span!r}"
    assert json.loads(span) == {"a": [1, 2], "b": {"c": 3}}
