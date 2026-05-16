"""LLM behaviors subpackage. CONTRACT v0.6.

Public surface:

  LLMProvider            — Protocol every provider implements
  LLMMessage             — single role-tagged message
  LLMResponse            — what `complete()` returns
  AnthropicProvider      — reference implementation
  RecordedLLMProvider    — fixture-backed provider for tests
  RecordingLLMProvider   — wraps another provider, persists responses
                           as fixtures (for first-time test seed)
  LLMCache               — content-keyed replay cache
  AssembledPrompt        — the deterministic prompt + params blob
                           returned by `LLMBehavior.build_prompt`
  MissingProviderError   — raised when an @llm_behavior is registered
                           without a runtime provider
  LLMBehaviorError       — structured failure carrier from @llm_behavior
                           wrappers; runtime turns it into
                           `behavior.failed` with a `reason`
"""

from activegraph.llm.anthropic import AnthropicProvider
from activegraph.llm.cache import LLMCache
from activegraph.llm.errors import LLMBehaviorError, MissingProviderError
from activegraph.llm.prompt import (
    AssembledPrompt,
    assemble_prompt,
    schema_to_json,
    serialize_view,
)
from activegraph.llm.provider import LLMProvider
from activegraph.llm.recorded import RecordedLLMProvider, RecordingLLMProvider
from activegraph.llm.types import LLMMessage, LLMResponse, ToolCall


__all__ = [
    "AnthropicProvider",
    "AssembledPrompt",
    "LLMBehaviorError",
    "LLMCache",
    "LLMMessage",
    "LLMProvider",
    "LLMResponse",
    "MissingProviderError",
    "RecordedLLMProvider",
    "RecordingLLMProvider",
    "ToolCall",
    "assemble_prompt",
    "schema_to_json",
    "serialize_view",
]
