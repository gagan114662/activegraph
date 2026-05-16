"""In-memory EventStore. CONTRACT v0.5 #2.

Volatile, dict-backed. Useful for tests, for the default in-memory Runtime,
and as the reference implementation of the EventStore protocol.
"""

from __future__ import annotations

from typing import Iterator, Optional

from activegraph.core.event import Event


class InMemoryEventStore:
    def __init__(self, run_id: str = "run_mem") -> None:
        self.run_id = run_id
        self._events: list[Event] = []
        self._by_id: dict[str, int] = {}

    def append(self, event: Event) -> None:
        if event.id in self._by_id:
            raise ValueError(f"duplicate event id: {event.id}")
        self._by_id[event.id] = len(self._events)
        self._events.append(event)

    def iter_events(
        self,
        after: Optional[str] = None,
        until: Optional[str] = None,
    ) -> Iterator[Event]:
        start = 0
        end = len(self._events)
        if after is not None:
            if after not in self._by_id:
                raise KeyError(f"unknown event id: {after}")
            start = self._by_id[after] + 1
        if until is not None:
            if until not in self._by_id:
                raise KeyError(f"unknown event id: {until}")
            end = self._by_id[until] + 1
        for i in range(start, end):
            yield self._events[i]

    def get_event(self, event_id: str) -> Optional[Event]:
        idx = self._by_id.get(event_id)
        if idx is None:
            return None
        return self._events[idx]

    def count(self) -> int:
        return len(self._events)

    def truncate_after(self, event_id: str) -> None:
        if event_id not in self._by_id:
            raise KeyError(f"unknown event id: {event_id}")
        cut = self._by_id[event_id] + 1
        dropped = self._events[cut:]
        self._events = self._events[:cut]
        for ev in dropped:
            del self._by_id[ev.id]

    def close(self) -> None:
        pass

    def __len__(self) -> int:
        return len(self._events)
