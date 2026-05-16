"""Behavior + RelationBehavior. Plain holders for metadata + the callable.

A Behavior is data, not magic. The decorator wraps a function in one of
these; class-based behaviors subclass directly. The runtime introspects
the metadata to match events and build views.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class Behavior:
    name: str
    fn: Callable[..., None]
    on: list[str] = field(default_factory=list)
    where: Optional[dict[str, Any]] = None
    view_spec: Optional[dict[str, Any]] = None
    creates: list[str] = field(default_factory=list)
    budget: Optional[dict[str, Any]] = None
    priority: int = 0  # reserved; v0 ties resolved by registration order

    def run(self, event, graph, ctx) -> None:
        self.fn(event, graph, ctx)


@dataclass
class RelationBehavior:
    name: str
    fn: Callable[..., None]
    relation_type: str
    on: list[str] = field(default_factory=list)
    where: Optional[dict[str, Any]] = None
    view_spec: Optional[dict[str, Any]] = None
    creates: list[str] = field(default_factory=list)
    budget: Optional[dict[str, Any]] = None
    priority: int = 0

    def run(self, relation, event, graph, ctx) -> None:
        self.fn(relation, event, graph, ctx)
