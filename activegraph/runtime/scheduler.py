"""Event-count scheduler for `activate_after`. CONTRACT v0.7 #13.

The decision: v0.7's `activate_after` is event-count only, never
wall-clock. Wall-clock would require a clock-source abstraction and
break determinism under replay. Event-count is deterministic across
replay, composes with the tick model, and the escape hatch ("user
drives `runtime.tick()` and injects timer.fired events") is the v1+
extension point if anyone needs wall-clock.

How it works:

  * When a triggering event matches a behavior with `activate_after=N`,
    the runtime calls `scheduler.schedule(...)` instead of invoking
    the behavior directly. A `behavior.scheduled` event is emitted.

  * The scheduler tracks each pending invocation with a fire-at-event
    counter (= current_event_count + N).

  * After every non-lifecycle event the runtime processes, it calls
    `scheduler.due(graph)` which returns the pending entries whose
    fire counters have been reached.

  * For each due entry, the runtime RE-CHECKS the `where=` clause
    against the latest graph state before invoking. If it no longer
    holds, the invocation is silently skipped (no extra event). If it
    holds, the behavior fires normally.

Parsing `activate_after`:
  * int → number of events
  * str "N" or "N events" / "N event" → N events
  * anything else → ValueError at registration time

Anything wall-clock (e.g. "5 minutes") is intentionally rejected with
a clear message pointing at CONTRACT v0.7 #13.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ScheduledEntry:
    behavior_name: str
    behavior_index: int  # registry index — preserves CONTRACT #10 order
    triggering_event_id: str
    fire_at_event_count: int
    where_recheck_path: Optional[str]  # behavior's `where=` payload path is kept
    scheduled_event_id: str  # the behavior.scheduled event id


@dataclass
class DelayedQueue:
    """Pending `activate_after` invocations. FIFO within the same fire tick."""

    entries: list[ScheduledEntry] = field(default_factory=list)

    def push(self, entry: ScheduledEntry) -> None:
        self.entries.append(entry)

    def pop_due(self, current_event_count: int) -> list[ScheduledEntry]:
        due: list[ScheduledEntry] = []
        kept: list[ScheduledEntry] = []
        for e in self.entries:
            if e.fire_at_event_count <= current_event_count:
                due.append(e)
            else:
                kept.append(e)
        self.entries = kept
        return due

    def __len__(self) -> int:
        return len(self.entries)


_DURATION_RE = re.compile(
    r"^\s*(\d+)\s*(events?)?\s*$", re.IGNORECASE
)
_WALL_CLOCK_WORDS = {
    "second", "seconds", "ms", "millisecond", "milliseconds",
    "minute", "minutes", "min", "mins",
    "hour", "hours", "day", "days", "week", "weeks",
}


def parse_activate_after(spec: Any) -> int:
    """Parse `activate_after=` into an integer event count.

    Accepts:
      - int N (N >= 1)
      - str "N", "N event", "N events"

    Rejects:
      - 0 or negative
      - any wall-clock unit (seconds, minutes, ...): wall-clock is
        intentionally out of scope for v0.7 (see CONTRACT v0.7 #13).
    """
    if isinstance(spec, bool):
        # bool is an int in Python — guard against accidental True/False.
        raise ValueError(f"activate_after must be a positive int, got {spec!r}")
    if isinstance(spec, int):
        n = spec
    elif isinstance(spec, str):
        s = spec.strip().lower()
        # Detect wall-clock units and reject with a CONTRACT-pointing message.
        for word in _WALL_CLOCK_WORDS:
            if word in s.split():
                raise ValueError(
                    f"activate_after={spec!r}: wall-clock units are not "
                    f"supported in v0.7 (CONTRACT v0.7 #13). Use an integer "
                    f"event count, e.g. activate_after=5 or '5 events'."
                )
        m = _DURATION_RE.match(s)
        if not m:
            raise ValueError(
                f"activate_after={spec!r}: expected int or 'N events', "
                f"got an unparseable string."
            )
        n = int(m.group(1))
    else:
        raise ValueError(
            f"activate_after={spec!r}: expected int or 'N events'."
        )
    if n < 1:
        raise ValueError(
            f"activate_after={spec!r}: must be >= 1 event."
        )
    return n
