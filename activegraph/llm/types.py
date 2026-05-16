"""LLM data types. Locked in v0.6.

These shapes are part of the v0.6 public contract:

  LLMMessage     — single role-tagged message in the conversation history.
  LLMResponse    — what every provider's `complete()` returns. Carries
                   raw text, parsed structured output (if a schema was
                   requested), token counts, cost, latency, model id,
                   finish reason, and a `cache_hit` flag the replay
                   layer sets when serving from recorded events.

Anything provider-specific (Anthropic stop reasons, retry-after
seconds, etc.) goes into the `provider_meta` dict so the contract
stays narrow.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal, Optional


Role = Literal["user", "assistant"]


@dataclass(frozen=True)
class LLMMessage:
    """One message in a chat-style prompt.

    Anthropic's `system` prompt is conventionally separate from the
    `messages` list, so we keep `system` out of this dataclass and pass
    it as its own argument to `LLMProvider.complete()`. That keeps the
    interface aligned with what the SDK actually wants.
    """

    role: Role
    content: str

    def to_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass
class LLMResponse:
    raw_text: str
    parsed: Optional[Any]
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal
    latency_seconds: float
    model: str
    finish_reason: str
    seed: Optional[int] = None
    cache_hit: bool = False
    provider_meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw_text": self.raw_text,
            "parsed": _parsed_to_jsonable(self.parsed),
            "input_tokens": int(self.input_tokens),
            "output_tokens": int(self.output_tokens),
            "cost_usd": str(self.cost_usd),
            "latency_seconds": float(self.latency_seconds),
            "model": self.model,
            "finish_reason": self.finish_reason,
            "seed": self.seed,
            "cache_hit": bool(self.cache_hit),
            "provider_meta": dict(self.provider_meta),
        }


def _parsed_to_jsonable(parsed: Any) -> Any:
    """Make a Pydantic model JSON-safe for event payloads."""
    if parsed is None:
        return None
    dump = getattr(parsed, "model_dump", None)
    if callable(dump):
        return dump()
    return parsed
