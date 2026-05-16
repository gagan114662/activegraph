"""Causal-chain audit. Walk back from an object through caused_by links
until we hit a goal.created (or an event with no parent).

CONTRACT v0.6 #15: when an object was created inside an @llm_behavior
handler, its provenance carries `llm_request_event_id`. The chain
follows that link first — showing the LLM round-trip (llm.requested
+ llm.responded with model and cost) — before continuing up through
the triggering event. The auditability story made concrete: a single
chain walk renders the full lineage from a claim back to the LLM call
that produced it, to the document it was extracted from, to the goal
that started the whole run.
"""

from __future__ import annotations

from typing import Any

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

    # If this object was created inside an @llm_behavior handler, the
    # provenance carries the llm.requested event id. Weave the LLM
    # round-trip into the chain at this point before continuing up
    # through the triggering event.
    llm_request_id = obj.provenance.get("llm_request_event_id")
    indent = "  "
    if llm_request_id:
        llm_req = by_id.get(llm_request_id)
        if llm_req is not None:
            llm_resp = _find_response_for(by_id, llm_request_id)
            actor = llm_req.actor or "?"
            model = llm_req.payload.get("model", "?")
            lines.append(
                f"{indent}← {actor} ({llm_req.id}) llm.requested  model={model}"
            )
            if llm_resp is not None:
                cost = llm_resp.payload.get("cost_usd")
                cached = llm_resp.payload.get("cache_hit")
                tail = " (cache_hit)" if cached else (f" cost=${_fmt_money(cost)}" if cost else "")
                lines.append(
                    f"{indent}  ({llm_resp.id}) llm.responded{tail}"
                )

    seen: set[str] = set()
    cursor = created_by_evt
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


def _find_response_for(by_id: dict[str, Event], request_id: str) -> Event | None:
    for e in by_id.values():
        if e.type == "llm.responded" and e.caused_by == request_id:
            return e
    return None


def _fmt_money(v: Any) -> str:
    try:
        return f"{float(v):.3f}"
    except (TypeError, ValueError):
        return str(v)
