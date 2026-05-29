"""Runtime introspection — RuntimeStatus and friends. CONTRACT v0.8 #11.

``runtime.status(recent=N)`` returns a ``RuntimeStatus``: a frozen
snapshot. Cheap to call (no graph traversal, no event log scan), safe
from anywhere, returns immutable data. The CLI's ``inspect`` command is
a thin wrapper around this.

There is no ``last_error`` field. Errors are events; filter
``recent_events`` for type ``behavior.failed``, or query the store for
a window-independent view. Convenience accessors that look the same as
the source of truth but mean different things are bug-bait.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from types import MappingProxyType
from typing import Any, Literal, Optional


RuntimeState = Literal["idle", "running", "stopped", "exhausted"]


@dataclass(frozen=True)
class BudgetSnapshot:
    used: Mapping[str, float]
    limits: Mapping[str, Optional[float]]
    cost_used_usd: str
    cost_limit_usd: Optional[str]
    exhausted_by: Optional[str]

    def __post_init__(self) -> None:
        # The module/`status()` docstrings promise the snapshot is
        # immutable ("mutating any field raises"). The dataclass freeze
        # only protects top-level assignment; the `used` / `limits`
        # mappings would still be mutable plain dicts. Wrap them in
        # read-only views so item assignment raises `TypeError`, making
        # the documented immutability guarantee actually hold.
        object.__setattr__(self, "used", MappingProxyType(dict(self.used)))
        object.__setattr__(self, "limits", MappingProxyType(dict(self.limits)))


@dataclass(frozen=True)
class FrameSnapshot:
    id: Optional[str]
    name: Optional[str]


@dataclass(frozen=True)
class BehaviorInfo:
    name: str
    kind: str  # "function" | "relation" | "llm"
    subscribed_to: tuple[str, ...]
    pattern: Optional[str] = None
    activate_after: Optional[int] = None


@dataclass(frozen=True)
class EventSummary:
    id: str
    type: str
    actor: Optional[str]
    timestamp: str


@dataclass(frozen=True)
class RuntimeStatus:
    run_id: str
    state: RuntimeState
    queue_depth: int
    events_processed: int
    budget: BudgetSnapshot
    frame: Optional[FrameSnapshot]
    registered_behaviors: tuple[BehaviorInfo, ...]
    recent_events: tuple[EventSummary, ...]


def status_to_dict(status: RuntimeStatus) -> dict[str, Any]:
    """Convert a RuntimeStatus to a plain JSON-serializable dict.

    Used by the CLI's --json flag. Field names match the documented
    schema; nested dataclasses become nested dicts.
    """
    return _asdict_with_tuples(status)


def _asdict_with_tuples(obj: Any) -> Any:
    # Recurse over dataclass fields by hand rather than via
    # `dataclasses.asdict`: the snapshot's `used` / `limits` are
    # `MappingProxyType` views (immutability guarantee), and `asdict`
    # deep-copies field values, which cannot pickle a mappingproxy.
    if is_dataclass(obj) and not isinstance(obj, type):
        return {
            f.name: _asdict_with_tuples(getattr(obj, f.name))
            for f in fields(obj)
        }
    if isinstance(obj, (list, tuple)):
        return [_asdict_with_tuples(v) for v in obj]
    if isinstance(obj, Mapping):
        return {k: _asdict_with_tuples(v) for k, v in obj.items()}
    return obj
