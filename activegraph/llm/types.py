"""LLM data types. Locked in v0.6, extended in v0.7.

These shapes are part of the public contract:

  LLMMessage     — single role-tagged message in the conversation history.
                   v0.7 adds the "tool" role and `tool_use_id` so the
                   LLM ↔ tool turn loop can echo results back.
  ToolCall       — a single tool-call request returned by the model
                   inside an `LLMResponse.tool_calls`. v0.7 addition.
  LLMResponse    — what every provider's `complete()` returns. Carries
                   raw text, parsed structured output (if a schema was
                   requested), token counts, cost, latency, model id,
                   finish reason, a `cache_hit` flag, and (v0.7) an
                   optional list of `tool_calls`.

Anything provider-specific (Anthropic stop reasons, retry-after
seconds, etc.) goes into the `provider_meta` dict so the contract
stays narrow.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal, Optional


# v0.7: the assistant can return tool_use blocks; the user echoes results
# back as a "tool" message. Anthropic uses content blocks with a
# `tool_use_id`; we flatten to a string content + carry the id alongside.
Role = Literal["user", "assistant", "tool"]


@dataclass(frozen=True)
class LLMMessage:
    """One message in a chat-style prompt.

    Anthropic's `system` prompt is conventionally separate from the
    `messages` list, so we keep `system` out of this dataclass and pass
    it as its own argument to `LLMProvider.complete()`. That keeps the
    interface aligned with what the SDK actually wants.

    CONTRACT v0.7: a `role="tool"` message echoes a tool result back to
    the model. `tool_use_id` ties it to the originating tool_use block
    from the previous assistant turn.
    """

    role: Role
    content: str
    tool_use_id: Optional[str] = None
    tool_name: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.tool_use_id is not None:
            out["tool_use_id"] = self.tool_use_id
        if self.tool_name is not None:
            out["tool_name"] = self.tool_name
        return out


@dataclass(frozen=True)
class ToolCall:
    """A single tool-call request returned inside `LLMResponse.tool_calls`.

    `id` is the provider-assigned identifier the assistant uses to
    match up its tool_use block with the following tool result; the
    runtime forwards it back as `LLMMessage.tool_use_id`. `name`
    matches the tool's `@tool(name=...)`. `args` is the JSON-shaped
    argument payload.
    """

    id: str
    name: str
    args: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "args": dict(self.args)}


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
    # v0.7: when finish_reason indicates the model wants to call tools,
    # `tool_calls` is non-empty and the runtime enters the turn loop
    # instead of handing `parsed` to the handler.
    tool_calls: Optional[list[ToolCall]] = None

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
            "tool_calls": (
                [tc.to_dict() for tc in self.tool_calls]
                if self.tool_calls
                else None
            ),
        }


def _parsed_to_jsonable(parsed: Any) -> Any:
    """Make a Pydantic model JSON-safe for event payloads."""
    if parsed is None:
        return None
    dump = getattr(parsed, "model_dump", None)
    if callable(dump):
        try:
            return dump(mode="json")
        except TypeError:
            return dump()
    return parsed
