"""Pluggable event-log stores. CONTRACT v0.5 #2.

Two implementations ship in v0.5:
- InMemoryEventStore: default, volatile, used by tests and ephemeral runs.
- SQLiteEventStore: durable persistence in a single file. Supports multiple
  runs (originals, forks, forks-of-forks) sharing one file.

The EventStore protocol lives in `store.base`. Custom backends conform to
that protocol; nothing in the runtime imports concrete stores directly.
"""

from activegraph.store.base import EventStore, RunRecord, replay_into
from activegraph.store.memory import InMemoryEventStore
from activegraph.store.serde import NonSerializableEventError
from activegraph.store.sqlite import SQLiteEventStore

__all__ = [
    "EventStore",
    "InMemoryEventStore",
    "NonSerializableEventError",
    "RunRecord",
    "SQLiteEventStore",
    "replay_into",
]
