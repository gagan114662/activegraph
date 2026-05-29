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
        # The class contract is that the clock "monotonically advances ... on
        # every call". A non-positive step would move now() backward (negative)
        # or stall it (zero), both of which break monotonicity, so refuse to
        # construct a clock that cannot honor its documented invariant.
        if step_seconds < 1:
            raise ValueError(
                f"step_seconds must be >= 1 to keep TickingClock monotonic, "
                f"got {step_seconds!r}"
            )
        parsed = datetime.fromisoformat(start.replace("Z", "+00:00"))
        # Honor the inherited Clock contract ("Real wall-clock UTC, Z suffix"):
        # normalize the start to UTC so now() always emits a Z-suffixed UTC
        # stamp. A naive start is assumed UTC; an offset start is converted.
        # Without this, now() passes through the caller's timezone and a naive
        # or non-UTC start yields a non-Z / non-UTC string that corrupts the
        # documented event-log timestamp format.
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        else:
            parsed = parsed.astimezone(timezone.utc)
        self._t = parsed
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
