"""Read-only scoped slice of the graph passed to behaviors as ctx.view.

CONTRACT #11: behaviors do not build their own views via graph.query —
they declare what they want via decorator metadata and the runtime
constructs a View before invocation.
"""

from __future__ import annotations

from typing import Any, Optional

from activegraph.core.event import Event
from activegraph.core.graph import Object, Relation, evaluate_where


class View:
    """Read-only scoped slice of the graph passed to behaviors. Provides filtered access to objects, relations, and events matching behavior-declared criteria."""

    def __init__(
        self,
        objects: list[Object],
        relations: list[Relation],
        events: list[Event],
    ) -> None:
        self._objects = objects
        self._relations = relations
        self._events = events

    def objects(
        self,
        type: Optional[str] = None,
        where: Optional[dict[str, Any]] = None,
    ) -> list[Object]:
        out = self._objects
        if type is not None:
            out = [o for o in out if o.type == type]
        if where:
            out = [o for o in out if evaluate_where(where, _object_root(o))]
        return list(out)

    def relations(self: "View", type: Optional[str] = None) -> list[Relation]:
        """Return relations visible in this view, optionally filtered by type.

        Args:
            type: Optional relation type to include.

        Returns:
            Relations matching the view scope and optional type filter.
        """
        out = self._relations
        if type is not None:
            out = [r for r in out if r.type == type]
        return list(out)

    def events(self: "View", type: Optional[str] = None) -> list[Event]:
        """Return events visible in this view, optionally filtered by type.

        Args:
            type: Optional event type to include.

        Returns:
            Events matching the view scope and optional type filter.
        """
        out = self._events
        if type is not None:
            out = [e for e in out if e.type == type]
        return list(out)


def _object_root(o: Object) -> dict[str, Any]:
    return {
        "id": o.id,
        "type": o.type,
        "data": o.data,
        "version": o.version,
        "provenance": o.provenance,
    }
