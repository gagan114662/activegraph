"""@behavior and @relation_behavior decorators + the global registry.

CONTRACT #6: signature is (event, graph, ctx) -> None — no return type.

The global registry exists so the README quickstart works without an
explicit `behaviors=[...]` list. `Runtime(graph)` reads the global
registry by default; passing `behaviors=[...]` overrides it. Tests
that need isolation can call `clear_registry()`.
"""

from __future__ import annotations

from typing import Any, Callable, Optional, Union

from activegraph.behaviors.base import Behavior, RelationBehavior


_REGISTRY: list[Union[Behavior, RelationBehavior]] = []


def clear_registry() -> None:
    _REGISTRY.clear()


def get_registry() -> list[Union[Behavior, RelationBehavior]]:
    return list(_REGISTRY)


def behavior(
    name: Optional[str] = None,
    on: Optional[list[str]] = None,
    where: Optional[dict[str, Any]] = None,
    view: Optional[dict[str, Any]] = None,
    creates: Optional[list[str]] = None,
    budget: Optional[dict[str, Any]] = None,
    priority: int = 0,
) -> Callable[[Callable], Behavior]:
    """Decorate a function as an event-driven behavior."""

    def wrap(fn: Callable) -> Behavior:
        b = Behavior(
            name=name or fn.__name__,
            fn=fn,
            on=list(on or []),
            where=dict(where) if where else None,
            view_spec=dict(view) if view else None,
            creates=list(creates or []),
            budget=dict(budget) if budget else None,
            priority=priority,
        )
        _REGISTRY.append(b)
        return b

    return wrap


def relation_behavior(
    relation_type: str,
    on: Optional[list[str]] = None,
    name: Optional[str] = None,
    where: Optional[dict[str, Any]] = None,
    view: Optional[dict[str, Any]] = None,
    creates: Optional[list[str]] = None,
    budget: Optional[dict[str, Any]] = None,
    priority: int = 0,
) -> Callable[[Callable], RelationBehavior]:
    """Decorate a function as a relation behavior — fires once per matching edge."""

    def wrap(fn: Callable) -> RelationBehavior:
        rb = RelationBehavior(
            name=name or fn.__name__,
            fn=fn,
            relation_type=relation_type,
            on=list(on or []),
            where=dict(where) if where else None,
            view_spec=dict(view) if view else None,
            creates=list(creates or []),
            budget=dict(budget) if budget else None,
            priority=priority,
        )
        _REGISTRY.append(rb)
        return rb

    return wrap
