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


def _first_balanced_span(text: str) -> Optional[str]:
    """Return the first balanced ``{...}`` or ``[...]`` span in ``text``.

    Scans for the first ``{`` or ``[`` and returns the substring up to its
    matching close bracket, tracking nesting and ignoring brackets that appear
    inside JSON string literals (with escape handling). Returns ``None`` when
    no opening bracket exists or it never closes.

    This replaces a greedy ``(\\{.*\\}|\\[.*\\])`` regex that matched from the
    first opening bracket to the *last* closing bracket anywhere in the text —
    which over-grabbed trailing prose (e.g. a stray ``}`` after the JSON) and
    broke the docstring's promise to recover the *first balanced* span.
    """
    open_to_close = {"{": "}", "[": "]"}
    # Locate the first opening bracket, but skip brackets inside string
    # literals (with escape handling) so a stray `{`/`[` in leading prose
    # quotes does not become the span start — honoring the docstring's
    # promise to ignore brackets that appear inside JSON string literals.
    start = None
    in_str = False
    escaped = False
    for i, ch in enumerate(text):
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
        elif ch in open_to_close:
            start = i
            break
    if start is None:
        return None

    opener = text[start]
    # Track EVERY bracket type with a stack — not just the outer opener's
    # type — so a balanced span honors the docstring's promise ("the first
    # balanced ``{...}`` or ``[...]`` span", "tracking nesting"). The old
    # code only counted depth for the outer bracket type, so an inner
    # ``[``/``{`` that never closed could be closed-over by the outer
    # bracket's matching close, yielding an UNbalanced span (e.g. `{"a": [1}`
    # closed at the `}` while the inner `[` dangled). A close that does not
    # match the top of the stack means the brackets are not balanced from
    # this start — abandon and keep scanning for a later balanced span.
    close_to_open = {c: o for o, c in open_to_close.items()}
    stack: list[str] = []
    in_str = False
    escaped = False
    for j in range(start, len(text)):
        ch = text[j]
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
        elif ch in open_to_close:
            stack.append(ch)
        elif ch in close_to_open:
            if not stack or stack[-1] != close_to_open[ch]:
                # Mismatched close (e.g. outer `{` meeting `}` while an inner
                # `[` is still open) — the span from `start` cannot be
                # balanced. Restart the search after this opener.
                return _first_balanced_span(text[start + 1 :])
            stack.pop()
            if not stack:
                return text[start : j + 1]
    return None


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
        m = _FENCED_JSON_RE.search(text)
        span = m.group(1) if m else _first_balanced_span(text)
        if span is not None:
            try:
                obj = json.loads(span)
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
