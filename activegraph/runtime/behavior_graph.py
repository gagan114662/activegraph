"""Constrained graph wrapper passed to behaviors. CONTRACT #7.

Allowed methods: add_object, add_relation, patch_object, propose_patch, emit.
The wrapper stamps actor / caused_by / frame_id automatically (CONTRACT #5)
and counts mutations so the runtime can report them in behavior.completed.

Behaviors get this object as their `graph` argument — never the raw Graph.
"""

from __future__ import annotations

from typing import Any, Optional

from activegraph.core.event import Event
from activegraph.core.graph import Graph, Object, Relation
from activegraph.core.patch import Patch


class Counters:
    __slots__ = ("objects_created", "relations_created", "patches_applied", "patches_proposed", "events_emitted")

    def __init__(self) -> None:
        self.objects_created = 0
        self.relations_created = 0
        self.patches_applied = 0
        self.patches_proposed = 0
        self.events_emitted = 0  # user-emitted via emit(), not graph mutations


class BehaviorGraph:
    def __init__(
        self,
        graph: Graph,
        *,
        actor: str,
        caused_by: Optional[str],
        frame_id: Optional[str],
    ) -> None:
        self._graph = graph
        self._actor = actor
        self._caused_by = caused_by
        self._frame_id = frame_id
        self.counters = Counters()

    # ---- mutators ----

    def add_object(self, type: str, data: dict[str, Any]) -> Object:
        obj = self._graph.add_object(
            type=type,
            data=data,
            actor=self._actor,
            caused_by=self._caused_by,
            frame_id=self._frame_id,
        )
        self.counters.objects_created += 1
        return obj

    def add_relation(
        self,
        source: str,
        target: str,
        type: str,
        data: Optional[dict[str, Any]] = None,
    ) -> Relation:
        rel = self._graph.add_relation(
            source=source,
            target=target,
            type=type,
            data=data,
            actor=self._actor,
            caused_by=self._caused_by,
            frame_id=self._frame_id,
        )
        self.counters.relations_created += 1
        return rel

    def patch_object(self, target: str, updates: dict[str, Any]) -> Patch:
        patch = self._graph.patch_object(
            target=target,
            updates=updates,
            actor=self._actor,
            caused_by=self._caused_by,
            frame_id=self._frame_id,
        )
        self.counters.patches_applied += 1
        return patch

    def propose_patch(
        self,
        target: str,
        op: str = "update",
        value: Optional[dict[str, Any]] = None,
        rationale: Optional[str] = None,
        evidence: Optional[list[str]] = None,
    ) -> Patch:
        patch = self._graph.propose_patch(
            target=target,
            op=op,
            value=value or {},
            proposed_by=self._actor,
            rationale=rationale,
            evidence=evidence,
            caused_by=self._caused_by,
            frame_id=self._frame_id,
        )
        self.counters.patches_proposed += 1
        return patch

    def emit(self, event_type: str, payload: dict[str, Any]) -> Event:
        ev = Event(
            id=self._graph.ids.event(),
            type=event_type,
            payload=dict(payload),
            actor=self._actor,
            frame_id=self._frame_id,
            caused_by=self._caused_by,
            timestamp=self._graph.clock.now(),
        )
        self._graph.emit(ev)
        self.counters.events_emitted += 1
        return ev

    # ---- read passthroughs (not iteration; that goes through ctx.view) ----

    def get_object(self, id_: str) -> Optional[Object]:
        return self._graph.get_object(id_)

    def get_relation(self, id_: str) -> Optional[Relation]:
        return self._graph.get_relation(id_)
