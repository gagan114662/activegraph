"""Runtime errors. CONTRACT v0.5 #7 (replay strictness)."""

from __future__ import annotations


class ReplayDivergenceError(RuntimeError):
    """Raised by `replay_strict=True` when a re-run produces a different
    event stream than the recorded log.

    `event_id` is the first offending event id (the recorded id at the
    position where divergence happened). `expected` describes the recorded
    event, `actual` describes what the re-run produced (or None if the
    re-run finished early).
    """

    def __init__(self, event_id: str, expected: str, actual: str | None) -> None:
        self.event_id = event_id
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"replay divergence at {event_id}: expected {expected!r}, got {actual!r}"
        )
