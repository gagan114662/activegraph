"""The `LLMProvider` Protocol every provider implements.

CONTRACT v0.6 #3, extended in v0.7. Narrow, explicit, keyword-only.
Shipped reference implementation is `AnthropicProvider`. Tests use
`RecordedLLMProvider` + `RecordingLLMProvider`. The demo ships its
own scripted provider.

A provider does three things:
  * `complete()`: run a single non-streaming completion. v0.7 adds
    an optional `tools=` parameter; when non-empty, the model is
    allowed to return tool_use blocks in the response.
  * `estimate_cost()`: turn token counts into USD (Decimal).
  * `count_tokens()`: provider-official input token count for the
    prompt that's about to be sent. Used for pre-call budget gating
    when `budget.max_cost_usd` is set; otherwise skipped (see
    CONTRACT v0.6 #4 / decision 10).

No streaming, no multi-model orchestration — those are deferred to
v0.8+. Tool use IS in v0.7, but the loop is orchestrated by the
runtime, not the provider: provider returns `tool_calls`, runtime
invokes the tool, runtime re-calls `complete()` with the result
echoed back as a `role="tool"` message.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Optional, Protocol, runtime_checkable

from activegraph.llm.types import LLMMessage, LLMResponse


@runtime_checkable
class LLMProvider(Protocol):
    def complete(
        self,
        *,
        system: str,
        messages: list[LLMMessage],
        model: str,
        max_tokens: int,
        temperature: float,
        top_p: float,
        output_schema: Optional[type],
        timeout_seconds: float,
        tools: Optional[list[dict[str, Any]]] = None,
    ) -> LLMResponse:
        ...

    def estimate_cost(
        self,
        *,
        input_tokens: int,
        output_tokens: int,
        model: str,
    ) -> Decimal:
        ...

    def count_tokens(
        self,
        *,
        system: str,
        messages: list[LLMMessage],
        model: str,
    ) -> int:
        ...
