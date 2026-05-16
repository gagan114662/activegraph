"""Shared LLM test helpers — providers that work without network and
small Pydantic schemas used across the v0.6 test suite.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Callable, Optional

from pydantic import BaseModel

from activegraph.llm import LLMMessage, LLMResponse


class Claim(BaseModel):
    text: str
    confidence: float


class ClaimList(BaseModel):
    claims: list[Claim]


@dataclass
class ScriptedProvider:
    """LLM provider that returns canned responses based on a callable.

    `respond_fn(messages, output_schema) -> dict | BaseModel` decides
    what the model "said". The provider boxes it into an LLMResponse.
    Useful for tests that want to control exactly what the model
    returns without recording fixtures.

    `call_log` captures every invocation so tests can assert call
    counts (e.g. "0 calls happened in the cached fork").
    """

    respond_fn: Callable[[list[LLMMessage], Optional[type]], Any]
    call_log: list[dict] = field(default_factory=list)
    token_count_log: list[dict] = field(default_factory=list)
    fixed_cost: Decimal = Decimal("0.0012")

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
    ) -> LLMResponse:
        self.call_log.append(
            {
                "system": system,
                "messages": [m.to_dict() for m in messages],
                "model": model,
                "temperature": temperature,
                "top_p": top_p,
                "output_schema": output_schema,
                "max_tokens": max_tokens,
                "timeout_seconds": timeout_seconds,
            }
        )
        out = self.respond_fn(messages, output_schema)
        if isinstance(out, BaseModel):
            raw = out.model_dump_json()
            parsed = out
        elif out is None:
            raw = ""
            parsed = None
        else:
            raw = json.dumps(out, sort_keys=True)
            parsed = (
                output_schema.model_validate(out) if output_schema is not None else out
            )
        return LLMResponse(
            raw_text=raw,
            parsed=parsed,
            input_tokens=42,
            output_tokens=11,
            cost_usd=self.fixed_cost,
            latency_seconds=0.012,
            model=model,
            finish_reason="end_turn",
        )

    def estimate_cost(
        self, *, input_tokens: int, output_tokens: int, model: str
    ) -> Decimal:
        return self.fixed_cost

    def count_tokens(
        self, *, system: str, messages: list[LLMMessage], model: str
    ) -> int:
        self.token_count_log.append(
            {"system": system, "messages": [m.to_dict() for m in messages]}
        )
        total = len(system) + sum(len(m.content) for m in messages)
        return max(1, total // 4)


class FailingProvider:
    """LLMProvider whose `complete()` always raises a chosen exception.

    Lets tests exercise the network/rate-limit/parse failure mappings.
    """

    def __init__(self, exc: BaseException, *, count_tokens_raises: bool = False):
        self.exc = exc
        self.count_tokens_raises = count_tokens_raises
        self.call_log: list[Any] = []

    def complete(self, **kwargs):
        self.call_log.append(kwargs)
        raise self.exc

    def estimate_cost(self, *, input_tokens, output_tokens, model):
        return Decimal("0.01")

    def count_tokens(self, **kwargs):
        if self.count_tokens_raises:
            raise self.exc
        return 100
