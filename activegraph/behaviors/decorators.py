"""@behavior, @relation_behavior, and @llm_behavior decorators
plus the global registry.

CONTRACT #6: regular behavior signature is (event, graph, ctx) -> None.
CONTRACT v0.6 #2: @llm_behavior handler signature is
(event, graph, ctx, llm_output) -> None — the 4th arg is bound by the
decorator's wrapper, not by the runtime.

The global registry exists so the README quickstart works without an
explicit `behaviors=[...]` list. `Runtime(graph)` reads the global
registry by default; passing `behaviors=[...]` overrides it. Tests
that need isolation can call `clear_registry()`.
"""

from __future__ import annotations

from typing import Any, Callable, Optional, Union

from activegraph.behaviors.base import (
    Behavior,
    LLMBehavior,
    RelationBehavior,
    _llm_behavior_fn_placeholder,
)


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


def llm_behavior(
    *,
    name: Optional[str] = None,
    on: Optional[list[str]] = None,
    where: Optional[dict[str, Any]] = None,
    description: str = "",
    model: str = "claude-sonnet-4-5",
    output_schema: Optional[type] = None,
    view: Optional[dict[str, Any]] = None,
    creates: Optional[list[str]] = None,
    budget: Optional[dict[str, Any]] = None,
    deterministic: bool = False,
    max_tokens: int = 4096,
    temperature: float = 0.7,
    top_p: float = 1.0,
    timeout_seconds: float = 60.0,
    prompt_template: Optional[str] = None,
    priority: int = 0,
) -> Callable[[Callable], LLMBehavior]:
    """Decorate a function as an LLM-driven behavior.

    The decorated function's signature is
    `(event, graph, ctx, llm_output) -> None`. The runtime assembles
    the prompt, calls the provider, parses the structured output, and
    only then invokes the handler with the parsed result. Failures
    flow as `behavior.failed` events with a `reason` from
    CONTRACT v0.6 #11 (`llm.parse_error`, `llm.schema_violation`,
    `llm.network_error`, `llm.rate_limited`, `budget.cost_exhausted`).

    Keyword-only on purpose — `@llm_behavior` carries enough
    parameters that positional binding would be a footgun.
    """

    def wrap(fn: Callable) -> LLMBehavior:
        b = LLMBehavior(
            name=name or fn.__name__,
            fn=_llm_behavior_fn_placeholder,
            on=list(on or []),
            where=dict(where) if where else None,
            view_spec=dict(view) if view else None,
            creates=list(creates or []),
            budget=dict(budget) if budget else None,
            priority=priority,
            handler=fn,
            description=description,
            model=model,
            output_schema=output_schema,
            deterministic=deterministic,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            timeout_seconds=timeout_seconds,
            prompt_template=prompt_template,
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
