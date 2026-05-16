"""Tool-side errors. CONTRACT v0.7 #6.

  ToolError              — structured failure from a tool body, carries
                           a `reason` code that the runtime merges into
                           `tool.responded.payload.error` and into the
                           wrapping behavior's `behavior.failed` event.

  MissingToolError       — raised at registration (Runtime startup) when
                           an @llm_behavior declares a tool the runtime
                           cannot find.

  UnknownToolError       — raised when an LLM response asks for a tool
                           the behavior did not declare. Caught by the
                           runtime and surfaced as
                           `behavior.failed reason="tool.unknown_tool"`.
"""

from __future__ import annotations

from typing import Any, Optional


class MissingToolError(RuntimeError):
    """Raised at LLM-behavior registration when a tool name isn't registered."""


class UnknownToolError(RuntimeError):
    """Raised when an LLM response calls a tool the behavior didn't declare."""


class ToolError(Exception):
    """Structured failure from inside a tool invocation.

    `reason` must be one of the v0.7 codes:
      tool.timeout, tool.network_error, tool.invalid_input,
      tool.invalid_output, tool.execution_error,
      tool.unknown_tool, tool.fixture_missing,
      budget.tool_calls_exhausted, budget.cost_exhausted.
    """

    def __init__(
        self,
        reason: str,
        message: str,
        *,
        payload_extras: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.reason = reason
        self.payload_extras = dict(payload_extras or {})
