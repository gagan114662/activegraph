"""Clock abstraction. CONTRACT #8: behaviors get time via ctx.clock."""

from __future__ import annotations

from datetime import datetime, timezone


class Clock:
    """Real wall-clock UTC. ISO 8601 second precision, Z suffix."""

    def now(self: "Clock") -> str:
        """Return the current UTC timestamp.

        Returns:
            An ISO 8601 timestamp with second precision and a Z suffix.
        """
        return (
            datetime.now(tz=timezone.utc)
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z")
        )


class FrozenClock(Clock):
    """Always returns the same timestamp. For tests and snapshots."""

    def __init__(self, t: str = "2026-05-15T10:32:01Z") -> None:
        self._t = t

    def now(self: "FrozenClock") -> str:
        """Return the frozen timestamp.

        Returns:
            The configured ISO 8601 timestamp.
        """
        return self._t


class TickingClock(Clock):
    """Monotonically advances by `step` seconds on every call. For tests that
    care about ordering but don't want wall-clock noise."""

    def __init__(
        self,
        start: str = "2026-05-15T10:32:01Z",
        step_seconds: int = 1,
    ) -> None:
        self._t = datetime.fromisoformat(start.replace("Z", "+00:00"))
        self._step = step_seconds

    def now(self: "TickingClock") -> str:
        """Return the current timestamp and advance the clock.

        Returns:
            The current ISO 8601 timestamp before applying the configured step.
        """
        out = self._t.isoformat(timespec="seconds").replace("+00:00", "Z")
        from datetime import timedelta

        self._t = self._t + timedelta(seconds=self._step)
        return out
