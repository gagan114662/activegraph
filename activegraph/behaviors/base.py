"""Behavior + RelationBehavior + LLMBehavior. Plain holders for metadata
plus the callable.

A Behavior is data, not magic. The decorator wraps a function in one of
these; class-based behaviors subclass directly. The runtime introspects
the metadata to match events and build views.

CONTRACT v0.6 #2: an LLMBehavior is structurally a Behavior whose
invocation lifecycle is owned by the runtime — the developer-supplied
function is the 4-arg `handler` (event, graph, ctx, llm_output), NOT
the 3-arg `fn`. Per CONTRACT v0.6 #20, `LLMBehavior.build_prompt` is
public so a developer can inspect the exact bytes that would be sent
to the model without making a call.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Optional

if TYPE_CHECKING:
    from activegraph.core.event import Event
    from activegraph.core.graph import Graph
    from activegraph.frame import Frame
    from activegraph.llm.prompt import AssembledPrompt


def _llm_behavior_fn_placeholder(event, graph, ctx) -> None:  # pragma: no cover
    raise RuntimeError(
        "LLMBehavior.fn invoked directly. The runtime owns LLM behavior "
        "invocation via _invoke_llm; calling .run() bypasses prompt "
        "assembly, the provider, and the LLM event log. This is a bug."
    )


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


@dataclass
class LLMBehavior(Behavior):
    """A behavior whose body is an LLM call.

    The runtime owns prompt assembly, cache lookup, the provider call,
    event emission, and structured-output parsing. The developer's
    `handler` is invoked only after the LLM has responded (or a cached
    response was found) and the output was successfully parsed.
    """

    handler: Optional[Callable[..., None]] = None
    description: str = ""
    model: str = "claude-sonnet-4-5"
    output_schema: Optional[type] = None
    deterministic: bool = False
    max_tokens: int = 4096
    temperature: float = 0.7
    top_p: float = 1.0
    timeout_seconds: float = 60.0
    prompt_template: Optional[str] = None

    def build_prompt(
        self,
        event: "Event",
        graph: "Graph",
        *,
        frame: Optional["Frame"] = None,
    ) -> "AssembledPrompt":
        """Assemble the prompt that would be sent for this event.

        CONTRACT v0.6 #20 — public so a developer can inspect prompts
        without making an API call. Reproducible (pure over inputs);
        cheap (no I/O).
        """

        from activegraph.llm.prompt import assemble_prompt
        from activegraph.runtime.view_builder import (
            DEFAULT_RECENT_EVENTS,
            _resolve_event_path,
            build_view,
        )

        view = build_view(self, event, graph)
        around_id: Optional[str] = None
        depth: Optional[int] = None
        if self.view_spec:
            ar_expr = self.view_spec.get("around")
            if ar_expr:
                around_id = _resolve_event_path(ar_expr, event)
            depth = self.view_spec.get("depth")
        return assemble_prompt(
            behavior_name=self.name,
            description=self.description,
            model=self.model,
            output_schema=self.output_schema,
            creates=self.creates,
            view=view,
            event=event,
            frame=frame,
            around=around_id,
            depth=depth,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            top_p=self.top_p,
            deterministic=self.deterministic,
            prompt_template=self.prompt_template,
        )
