"""LLM-side errors. Two surface types:

  MissingProviderError    — raised at LLM-behavior registration time
                            when the runtime has no provider attached.
                            Fails loud, never silent (CONTRACT v0.6 #21).

  LLMBehaviorError        — raised by the @llm_behavior wrapper to
                            signal a structured failure with a
                            `reason` code from CONTRACT v0.6 #11. The
                            runtime's existing exception catch
                            recognizes this type and merges `reason`
                            + `payload_extras` into the
                            `behavior.failed` event.
"""

from __future__ import annotations

from typing import Any, Optional


class MissingProviderError(RuntimeError):
    """Raised when an @llm_behavior is invoked but no provider is wired."""


class LLMBehaviorError(Exception):
    """Carries a structured failure from inside an @llm_behavior wrapper.

    The runtime's `_invoke` catch reads `reason` and `payload_extras`
    off this exception and includes them in the emitted
    `behavior.failed` event. Other exception types fall through to
    the existing CONTRACT #13 path unchanged.
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
