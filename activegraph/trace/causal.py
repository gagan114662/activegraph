"""Causal-chain audit. Walk back from an object through caused_by links
until we hit a goal.created (or an event with no parent).
"""

from __future__ import annotations

from activegraph.core.event import Event
from activegraph.core.graph import Graph


def causal_chain(graph: Graph, object_id: str) -> str:
    obj = graph.get_object(object_id)
    if obj is None:
        return f"(no such object: {object_id})"

    by_id: dict[str, Event] = {e.id: e for e in graph.events}
    # Find the event that created this object.
    created_by_evt: Event | None = None
    for e in graph.events:
        if e.type == "object.created" and e.payload.get("object", {}).get("id") == object_id:
            created_by_evt = e
            break

    lines: list[str] = []
    label = obj.data.get("title") or obj.data.get("text") or ""
    label_s = f' "{label}"' if label else ""
    lines.append(f"{obj.id} ({obj.type}){label_s}")

    seen: set[str] = set()
    cursor = created_by_evt
    indent = "  "
    while cursor is not None:
        if cursor.id in seen:
            lines.append(f"{indent}← (cycle at {cursor.id})")
            break
        seen.add(cursor.id)
        actor = cursor.actor or "?"
        lines.append(f"{indent}← {actor} ({cursor.id}) {cursor.type}")
        if cursor.caused_by is None:
            break
        cursor = by_id.get(cursor.caused_by)
        indent += "  "

    return "\n".join(lines)
