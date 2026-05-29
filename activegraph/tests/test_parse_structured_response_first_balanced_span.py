r"""T7 repeat HARD 001 — docstring↔code drift in parse_structured_response.

The docstring of ``activegraph.llm.parsing.parse_structured_response`` documents
the extraction order as:

    try ``json.loads`` on the response verbatim; on failure, look for a fenced
    ``json`` block; on failure, grab the first balanced ``{...}`` / ``[...]``
    span.

and documents that ``reason="llm.parse_error"`` is raised only when
"no JSON found / ``json.loads`` failed" — i.e. when there is genuinely no
recoverable JSON.

The bug: the fallback regex ``_BRACE_RE = r"(\{.*\}|\[.*\])"`` (DOTALL) is
GREEDY. It does not grab the *first balanced* span — it grabs from the first
opening brace to the *last* closing brace anywhere in the text. When valid JSON
is followed by prose that contains a stray ``}`` (or ``]``), the captured span
includes the trailing junk, ``json.loads`` rejects it, and the function raises
``llm.parse_error`` ("no JSON found") even though a balanced JSON span the
docstring promises to recover IS present.

These tests assert the DOCUMENTED behavior: when a balanced JSON span is
present, it is found and parsed regardless of trailing prose.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from activegraph.llm.errors import LLMBehaviorError
from activegraph.llm.parsing import parse_structured_response


class _Model(BaseModel):
    a: int


def test_first_balanced_object_span_parsed_despite_trailing_brace() -> None:
    # A valid balanced {...} span followed by prose containing a stray brace.
    # The docstring promises the first balanced span is grabbed and parsed.
    text = 'The result is {"a": 1} -- end of data }'
    result = parse_structured_response(text, _Model)
    assert result.a == 1


def test_first_balanced_array_span_parsed_despite_trailing_bracket() -> None:
    class _ListModel(BaseModel):
        items: list[int]

    text = 'Answer: {"items": [1, 2, 3]} (note: ignore the next ] please)'
    result = parse_structured_response(text, _ListModel)
    assert result.items == [1, 2, 3]


def test_no_json_still_raises_parse_error() -> None:
    # Sanity: genuinely no JSON must still raise llm.parse_error. The fix must
    # not turn the parse_error path into a false success.
    with pytest.raises(LLMBehaviorError) as exc:
        parse_structured_response("there is no json here at all", _Model)
    assert exc.value.reason == "llm.parse_error"
