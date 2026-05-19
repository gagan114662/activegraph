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


def clear_registry() -> list[Union[Behavior, RelationBehavior]]:
    """Empty the global behavior registry and return what was cleared.

    Tests that need isolation between cases call this in a fixture; the
    return value is the list of removed behaviors in registration
    order, so multi-run scripts can capture them once and re-register
    via :func:`register` on each subsequent run without re-importing
    the modules whose ``@behavior`` decorators populated the registry
    in the first place. See the *Multi-run scripts* cookbook recipe.

    v1.0.1: the return value is new. v1.0 returned ``None``; callers
    that ignored the return still work unchanged.
    """
    cleared: list[Union[Behavior, RelationBehavior]] = list(_REGISTRY)
    _REGISTRY.clear()
    return cleared


def get_registry() -> list[Union[Behavior, RelationBehavior]]:
    """Snapshot of the global behavior registry (a shallow copy)."""
    return list(_REGISTRY)


def register(behavior_obj: Union[Behavior, RelationBehavior]) -> None:
    """Append an already-constructed behavior to the global registry.

    The decorators (:func:`behavior`, :func:`relation_behavior`,
    :func:`llm_behavior`) register on definition; this function exists
    for the case where definition and registration are decoupled —
    most commonly, multi-run scripts that call :func:`clear_registry`
    between runs and need to re-populate the registry without
    re-importing the decorator-bearing modules:

    .. code-block:: python

        from activegraph import clear_registry, register

        cleared = clear_registry()        # capture before the first run
        rt1 = Runtime(graph1); rt1.run_goal("first")

        for b in cleared:                 # restore for the next run
            register(b)
        rt2 = Runtime(graph2); rt2.run_goal("second")

    See the *Multi-run scripts* cookbook recipe.

    v1.0.1: new. v1.0 required reaching into the private
    ``_REGISTRY`` list — the user-test gate surfaced that as a rough
    edge.
    """
    if not isinstance(behavior_obj, (Behavior, RelationBehavior)):
        raise TypeError(
            f"register() expected a Behavior, RelationBehavior, or "
            f"LLMBehavior instance; got {type(behavior_obj).__name__}. "
            f"Use the @behavior / @relation_behavior / @llm_behavior "
            f"decorators to construct one."
        )
    _REGISTRY.append(behavior_obj)


def behavior(
    name: Optional[str] = None,
    on: Optional[list[str]] = None,
    where: Optional[dict[str, Any]] = None,
    view: Optional[dict[str, Any]] = None,
    creates: Optional[list[str]] = None,
    budget: Optional[dict[str, Any]] = None,
    priority: int = 0,
    *,
    pattern: Optional[str] = None,
    activate_after: Any = None,
) -> Callable[[Callable], Behavior]:
    """Decorate a function as an event-driven behavior.

    v0.7 additions (both keyword-only):
      - `pattern=`: a Cypher subset pattern string. When set, the
        behavior fires only when the pattern matches the post-event
        graph state. Combined with `on=` both conditions must hold
        (CONTRACT v0.7 #11). Matches are exposed as `ctx.matches`.
      - `activate_after=`: int event count or "N events". Delays
        invocation by N events; re-checks `where=` at fire time
        (CONTRACT v0.7 #13).
    """

    from activegraph.runtime.patterns import parse as _parse_pattern
    from activegraph.runtime.scheduler import parse_activate_after as _parse_aa

    compiled_matcher = None
    if pattern is not None:
        compiled_matcher = _parse_pattern(pattern).compile()
    delay_n: Optional[int] = None
    if activate_after is not None:
        delay_n = _parse_aa(activate_after)

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
            pattern=pattern,
            pattern_matcher=compiled_matcher,
            activate_after=delay_n,
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
    model: Optional[str] = None,
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
    pattern: Optional[str] = None,
    activate_after: Any = None,
    tools: Optional[list] = None,
    max_tool_turns: int = 6,
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

    ``model=`` is optional (v1.0.2 #1). Omitted, the runtime resolves
    it to the configured provider's ``default_model`` at registration
    time — ``"claude-sonnet-4-5"`` for ``AnthropicProvider``,
    ``"gpt-4o-mini"`` for ``OpenAIProvider``. Passing an explicit
    model string still works byte-identically; the runtime additionally
    validates the name against the configured provider's
    ``recognizes_model()`` and raises
    :class:`InvalidRuntimeConfiguration` at registration time if the
    name belongs to a different shipped provider's family (e.g.
    ``model="gpt-4o-mini"`` on a runtime configured with
    ``AnthropicProvider``). Names no shipped provider recognizes
    (custom or fine-tuned models) pass through silently.

    `prompt_template=` is the only escape hatch from the
    runtime-assembled prompt. It is a `str.format`-style template that
    receives four placeholders:

    - ``{system}`` — the system block: behavior name, frame goal and
      constraints, role description, and (when `output_schema=` is set)
      the schema with an example instance.
    - ``{view}`` — the scoped graph view: objects, relations, and
      recent events, rendered as Markdown (format locked per
      CONTRACT v0.6 #13).
    - ``{event}`` — the triggering event as id, type, actor, and
      pretty-printed JSON payload with volatile keys stripped.
    - ``{instruction}`` — the one-sentence task derived from `creates=`
      and `output_schema=`.

    The four placeholders carry the same runtime-assembled content
    whether or not a template is set; the template only re-arranges
    them. Omitting `prompt_template=` (the default) uses the
    runtime's canonical layout.
    """

    from activegraph.runtime.patterns import parse as _parse_pattern
    from activegraph.runtime.scheduler import parse_activate_after as _parse_aa

    compiled_matcher = None
    if pattern is not None:
        compiled_matcher = _parse_pattern(pattern).compile()
    delay_n: Optional[int] = None
    if activate_after is not None:
        delay_n = _parse_aa(activate_after)

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
            pattern=pattern,
            pattern_matcher=compiled_matcher,
            activate_after=delay_n,
            tools=list(tools) if tools else [],
            max_tool_turns=max_tool_turns,
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
    *,
    pattern: Optional[str] = None,
    activate_after: Any = None,
) -> Callable[[Callable], RelationBehavior]:
    """Decorate a function as a relation behavior — fires once per matching edge.

    v0.7: also accepts `pattern=` and `activate_after=` per CONTRACT
    v0.7 #8 / #11 / #13.
    """

    from activegraph.runtime.patterns import parse as _parse_pattern
    from activegraph.runtime.scheduler import parse_activate_after as _parse_aa

    compiled_matcher = None
    if pattern is not None:
        compiled_matcher = _parse_pattern(pattern).compile()
    delay_n: Optional[int] = None
    if activate_after is not None:
        delay_n = _parse_aa(activate_after)

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
            pattern=pattern,
            pattern_matcher=compiled_matcher,
            activate_after=delay_n,
        )
        _REGISTRY.append(rb)
        return rb

    return wrap
