"""Reference tool: graph_query. CONTRACT v0.7 #16.

`graph_query` is a tool whose body operates on the graph itself —
the demonstration that the tool primitive is general, not just an
"external API" escape hatch. It goes through the same event-sourced
invocation path as any other tool: `tool.requested` / `tool.responded`
events, the same cache, the same budget.

Per CONTRACT v0.7 #5, the `ToolContext` deliberately does NOT carry
a graph reference — tools that need the graph close over it via a
factory at registration time. `make_graph_query_tool(graph)` returns
a Tool bound to the supplied graph.

Per CONTRACT v0.7 #7 (tool-determinism decision), `graph_query` is
marked `deterministic=True`: given the same graph state, it returns
the same answer. But replay still serves from cache by default; the
`Runtime(replay_reinvoke_deterministic=True)` opt-in is what lets
deterministic tools actually re-invoke during replay. Reasoning:
even a deterministic tool's correctness depends on the reconstructed
graph state matching the recorded state at the moment of the call,
and that's a strong invariant — cheaper and more honest to serve
from cache.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Optional

from pydantic import BaseModel, Field

from activegraph.tools.base import Tool
from activegraph.tools.context import ToolContext


class ObjectRef(BaseModel):
    id: str
    type: str
    data: dict[str, Any] = Field(default_factory=dict)


class GraphQueryInput(BaseModel):
    object_type: str = Field(description="The object type to query.")
    where: Optional[dict[str, Any]] = Field(
        default=None,
        description=(
            "Optional filter: dotted-path keys, literal or {op: value} values. "
            "Same semantics as Graph.query(where=...)."
        ),
    )
    limit: int = Field(default=50, ge=1, le=500)


class GraphQueryOutput(BaseModel):
    refs: list[ObjectRef]
    truncated: bool = False


def make_graph_query_tool(graph) -> Tool:
    """Factory: produces a `graph_query` tool bound to the given Graph.

    Returns a Tool, NOT a registered callable — the caller is expected
    to either pass it directly into `@llm_behavior(tools=[...])` or
    into `Runtime(tools=[...])`. We do NOT push it into the global
    `@tool` registry: graph-bound tools are runtime-specific, and a
    global registry would silently couple tools to the first graph
    that constructed one.
    """

    def fn(args: GraphQueryInput, ctx: ToolContext) -> GraphQueryOutput:
        results = graph.query(object_type=args.object_type, where=args.where)
        truncated = len(results) > args.limit
        results = results[: args.limit]
        return GraphQueryOutput(
            refs=[
                ObjectRef(id=o.id, type=o.type, data=dict(o.data))
                for o in results
            ],
            truncated=truncated,
        )

    return Tool(
        name="graph_query",
        fn=fn,
        description=(
            "Query objects in the active graph by type and optional WHERE "
            "filter. Returns object id, type, and data for matching objects."
        ),
        input_schema=GraphQueryInput,
        output_schema=GraphQueryOutput,
        cost_per_call=Decimal("0"),
        timeout_seconds=1.0,
        deterministic=True,
    )
