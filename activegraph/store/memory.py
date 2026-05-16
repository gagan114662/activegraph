"""In-memory store. The Graph already keeps the log in a list; this exists
as a stable seam so v0.5's SQLite store can swap in without touching Graph.
"""

from __future__ import annotations

from activegraph.core.event import Event


class MemoryEventStore:
    def __init__(self) -> None:
        self._events: list[Event] = []

    def append(self, event: Event) -> None:
        self._events.append(event)

    def all(self) -> list[Event]:
        return list(self._events)

    def __len__(self) -> int:
        return len(self._events)
