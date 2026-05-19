"""Structured-output parsing shared across LLM providers.

CONTRACT v1.0.1 #5. Pulled out of ``activegraph.llm.anthropic`` when
:class:`activegraph.llm.openai.OpenAIProvider` landed and needed the
same JSON-extraction-then-Pydantic-validate path. The function is the
sole boundary between provider raw-text output and the framework's
typed downstream world: any future provider that wants to use the
framework's instruction-based structured-output path imports
:func:`parse_structured_response` here rather than reimplementing the
extraction heuristics.

The extraction order is the same one shipped with the original
Anthropic provider in v0.6: try ``json.loads`` on the response
verbatim; on failure, look for a fenced ``json`` block; on failure,
grab the first balanced ``{...}`` / ``[...]`` span. Two distinct
failure modes flow back as :class:`LLMBehaviorError`:

  reason=llm.parse_error       no JSON found / ``json.loads`` failed
  reason=llm.schema_violation  JSON found but Pydantic rejected it

Provider symmetry: AnthropicProvider and OpenAIProvider produce
identical errors for identical responses through this function.
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional

from activegraph.llm.errors import LLMBehaviorError


_FENCED_JSON_RE = re.compile(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", re.DOTALL)
_BRACE_RE = re.compile(r"(\{.*\}|\[.*\])", re.DOTALL)


def parse_structured_response(text: str, schema: type) -> Any:
    """Parse JSON out of an LLM response and validate against ``schema``.

    Raises :class:`LLMBehaviorError` with ``reason="llm.parse_error"``
    when no JSON is recoverable from ``text``, and with
    ``reason="llm.schema_violation"`` when JSON is recoverable but
    Pydantic rejects it against ``schema``.

    The behavior is the same one shipped in v0.6 with AnthropicProvider;
    v1.0.1 lifts it here so OpenAIProvider can call the same function
    and produce byte-identical structured errors for byte-identical
    responses.
    """
    candidate = text.strip()
    obj: Any = None
    parse_err: Optional[Exception] = None
    try:
        obj = json.loads(candidate)
    except Exception as e:
        parse_err = e
    if obj is None:
        m = _FENCED_JSON_RE.search(text) or _BRACE_RE.search(text)
        if m:
            try:
                obj = json.loads(m.group(1))
                parse_err = None
            except Exception as e:
                parse_err = e
    if obj is None:
        raise LLMBehaviorError(
            "llm.parse_error",
            f"no JSON found in response: {parse_err}",
            payload_extras={"raw_text": text, "underlying": str(parse_err)},
        )

    try:
        return schema.model_validate(obj)
    except Exception as e:
        raise LLMBehaviorError(
            "llm.schema_violation",
            f"response did not match schema {schema.__name__}: {e}",
            payload_extras={
                "raw_text": text,
                "schema": schema.__name__,
                "validation_errors": str(e),
            },
        ) from e
