"""T7 repeat-hard 009 — docstring↔code drift in parse_structured_response.

`activegraph/llm/parsing.py` documents EXACTLY two failure modes:

    reason=llm.parse_error       no JSON found / json.loads failed
    reason=llm.schema_violation  JSON found but Pydantic rejected it

The drift: when the model returns the bare JSON literal ``null``,
``json.loads("null")`` SUCCEEDS and returns the Python value ``None``.
JSON *was* recoverable — so per the docstring the value must flow to the
schema-validation step and, on rejection, raise ``llm.schema_violation``.

But the implementation uses ``obj is None`` as the "haven't parsed yet"
sentinel. The legitimately-parsed ``null`` value collides with that
sentinel, so the code falls through to the no-JSON branch and raises
``llm.parse_error`` ("no JSON found in response") — contradicting the
docstring, which reserves ``llm.parse_error`` for "no JSON is
recoverable from text".

These tests assert the DOCUMENTED behavior and fail against the buggy
code (which raises parse_error for a recoverable ``null``).
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from activegraph.llm.errors import LLMBehaviorError
from activegraph.llm.parsing import parse_structured_response


class _Schema(BaseModel):
    x: int


def test_bare_null_literal_is_schema_violation_not_parse_error() -> None:
    # `null` is valid, recoverable JSON. Per the docstring contract it is
    # NOT a parse_error — it parses fine, then fails the schema.
    with pytest.raises(LLMBehaviorError) as excinfo:
        parse_structured_response("null", _Schema)
    assert excinfo.value.reason == "llm.schema_violation", (
        "a recoverable JSON `null` that fails the schema must raise "
        "llm.schema_violation, not llm.parse_error"
    )


def test_whitespace_padded_null_literal_is_schema_violation() -> None:
    # The function strips before json.loads, so "  null  " also parses to
    # the JSON null value and must be treated identically.
    with pytest.raises(LLMBehaviorError) as excinfo:
        parse_structured_response("   null   ", _Schema)
    assert excinfo.value.reason == "llm.schema_violation"


def test_genuine_non_json_still_parse_error() -> None:
    # Guard the OTHER side of the contract: truly unrecoverable text must
    # still raise llm.parse_error. (Should pass before AND after the fix.)
    with pytest.raises(LLMBehaviorError) as excinfo:
        parse_structured_response("this is not json at all", _Schema)
    assert excinfo.value.reason == "llm.parse_error"
