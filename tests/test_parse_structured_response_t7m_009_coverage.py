"""T7 medium run 009 coverage for
``activegraph.llm.parsing.parse_structured_response``.

The function is the sole boundary between provider raw-text output and the
framework's typed downstream world (CONTRACT v1.0.1 #5). It has three
distinct behaviours that no existing test exercised:

  1. verbatim ``json.loads`` happy path  -> validated model instance
  2. fenced / embedded JSON extraction    -> validated model instance
  3. two failure modes flow back as ``LLMBehaviorError``:
       reason="llm.parse_error"     (no JSON recoverable)
       reason="llm.schema_violation"(JSON found, Pydantic rejected it)

These tests use the REAL parsing function and REAL Pydantic schemas — no
mock of the API under test.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from activegraph.llm.errors import LLMBehaviorError
from activegraph.llm.parsing import parse_structured_response


class _Person(BaseModel):
    name: str
    age: int


def test_activegraph_llm_parsing_parse_structured_response_verbatim_happy_path() -> None:
    """Verbatim JSON that matches the schema returns a validated model."""
    out = parse_structured_response('{"name": "Maya", "age": 30}', _Person)

    assert isinstance(out, _Person)
    assert out.name == "Maya"
    assert out.age == 30


def test_activegraph_llm_parsing_parse_structured_response_extracts_fenced_json() -> None:
    """JSON wrapped in prose / a fenced code block is still extracted.

    Exercises the second extraction path (_FENCED_JSON_RE / _BRACE_RE
    fallback) that the verbatim ``json.loads`` cannot reach.
    """
    text = (
        "Sure, here is the structured result you asked for:\n"
        "```json\n"
        '{"name": "Quinn", "age": 41}\n'
        "```\n"
        "Let me know if you need anything else."
    )
    out = parse_structured_response(text, _Person)

    assert isinstance(out, _Person)
    assert out.name == "Quinn"
    assert out.age == 41


def test_activegraph_llm_parsing_parse_structured_response_raises_parse_error_when_no_json() -> None:
    """No recoverable JSON -> LLMBehaviorError(reason='llm.parse_error')."""
    with pytest.raises(LLMBehaviorError) as excinfo:
        parse_structured_response("there is absolutely no json here", _Person)

    assert excinfo.value.reason == "llm.parse_error"
    # The raw text is carried back for downstream debugging.
    assert excinfo.value.payload_extras["raw_text"] == "there is absolutely no json here"


def test_activegraph_llm_parsing_parse_structured_response_raises_schema_violation_on_bad_shape() -> None:
    """Valid JSON that fails the schema -> reason='llm.schema_violation'.

    ``age`` is required and an int; omitting it (and supplying a wrong-typed
    field) is recoverable JSON but an invalid ``_Person``.
    """
    with pytest.raises(LLMBehaviorError) as excinfo:
        parse_structured_response('{"name": "Riley"}', _Person)

    assert excinfo.value.reason == "llm.schema_violation"
    assert excinfo.value.payload_extras["schema"] == "_Person"
