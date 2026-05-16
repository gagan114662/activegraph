"""Match events to behaviors. CONTRACT #10: registration order for ties."""

from __future__ import annotations

from typing import Iterable, Union

from activegraph.behaviors.base import Behavior, RelationBehavior
from activegraph.core.event import Event
from activegraph.core.graph import Graph, Relation, evaluate_where


BehaviorLike = Union[Behavior, RelationBehavior]


class Registry:
    def __init__(self, behaviors: Iterable[BehaviorLike]) -> None:
        self._behaviors: list[BehaviorLike] = list(behaviors)

    def all(self) -> list[BehaviorLike]:
        return list(self._behaviors)

    def match(
        self, event: Event, graph: Graph
    ) -> list[tuple[BehaviorLike, list[Relation]]]:
        """Return (behavior, matching_relations) pairs in registration order.

        For regular behaviors the relations list is empty. For relation
        behaviors it's the set of edges the runtime should iterate over —
        the behavior is invoked once per relation.
        """
        out: list[tuple[BehaviorLike, list[Relation]]] = []
        for b in self._behaviors:
            if event.type not in b.on:
                continue
            if isinstance(b, RelationBehavior):
                rels = _matching_relations(b, event, graph)
                if rels:
                    out.append((b, rels))
            else:
                if b.where and not evaluate_where(b.where, event.payload):
                    continue
                out.append((b, []))
        return out


def _matching_relations(
    rb: RelationBehavior, event: Event, graph: Graph
) -> list[Relation]:
    candidates = [r for r in graph.all_relations() if r.type == rb.relation_type]
    referenced = _collect_string_values(event.payload)
    out: list[Relation] = []
    for r in candidates:
        if r.source in referenced or r.target in referenced:
            if rb.where and not evaluate_where(rb.where, event.payload):
                continue
            out.append(r)
    return out


def _collect_string_values(obj) -> set[str]:
    out: set[str] = set()
    _walk(obj, out)
    return out


def _walk(obj, out: set[str]) -> None:
    if isinstance(obj, str):
        out.add(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            _walk(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _walk(v, out)
