"""Single in-process FIFO queue. CONTRACT #10: no priority, no async."""

from __future__ import annotations

from collections import deque
from typing import Optional

from activegraph.core.event import Event


class EventQueue:
    def __init__(self) -> None:
        self._q: deque[Event] = deque()

    def push(self, event: Event) -> None:
        self._q.append(event)

    def pop(self) -> Optional[Event]:
        if not self._q:
            return None
        return self._q.popleft()

    def __len__(self) -> int:
        return len(self._q)

    def __bool__(self) -> bool:
        return bool(self._q)
