"""The runtime loop. Single-threaded FIFO. CONTRACT #10.

Responsibilities (v0):
- Subscribe to graph events, enqueue them.
- Pop events, find matching behaviors, invoke each in registration order.
- Wrap behavior calls with behavior.started / behavior.completed
  (or relation_behavior.started / behavior.completed for relation behaviors).
- Catch any behavior exception, emit behavior.failed (CONTRACT #13).
- Stop on idle or budget exhaustion.

Added in v0.5:
- `persist_to=PATH` (sugar) or `store=...` attaches a durable EventStore.
- `Runtime.load(path, run_id=None)` rebuilds from an event log (CONTRACT v0.5 #5).
- `runtime.save_state(path=None)` flushes / late-binds persistence.
- `runtime.fork(at_event, label=None)` branches a run (#9).
- `runtime.diff(other)` returns a structural `Diff` (#10).
- `replay_strict=True` re-runs behaviors and verifies the output matches
  the recorded log; on the first divergence, raises ReplayDivergenceError
  (#7).

Added in v0.6:
- `llm_provider=` plugs an LLMProvider (Anthropic, recorded, scripted).
- `replay_llm_cache=True` pre-populates a content-keyed cache from
  recorded `llm.responded` events so re-runs (forks, strict-replay)
  do not call the API.
- The `_invoke_llm` path is the runtime-owned LLM lifecycle:
  assemble prompt → cache lookup → optional cost pre-check →
  emit llm.requested → call provider (or use cached) → emit
  llm.responded → parse output → invoke handler. Failures flow as
  `behavior.failed` with a `reason` from CONTRACT v0.6 #11.
- `replay_strict=True` + recorded llm.responded whose prompt hash
  does not match the live re-assembly → ReplayDivergenceError pinned
  to the offending llm.requested event id (decision-2 adjustment).

Added in v0.7:
- `tools=[t1, t2, ...]` plugs a list of `Tool` objects; absent tools
  fall back to the global `@tool` registry.
- The `_invoke_llm` path becomes a turn loop: provider's response can
  include `tool_calls`, in which case the runtime invokes the tool,
  echoes the result back into messages, and re-calls the provider.
  `max_tool_turns` caps the loop. Per-turn LLM and tool events are
  emitted; replay reads them back in order.
- `replay_tool_cache=True` (parallel to `replay_llm_cache=True`)
  pre-populates a content-keyed cache from `tool.responded` events.
  By default ALL tools (deterministic or not) serve from cache on
  replay; `replay_reinvoke_deterministic=True` opts in to actually
  re-invoking deterministic tools (CONTRACT v0.7 tool-determinism).
- `pattern=` on a behavior compiles a Cypher subset matcher; the
  registry's `match()` includes the bindings. Behaviors fire once
  per event when both `on=` and `pattern=` agree (CONTRACT v0.7 #11).
- `activate_after=N` schedules a behavior to fire N events later,
  with the `where=` re-checked at fire time (CONTRACT v0.7 #13).
"""

from __future__ import annotations

import json
import random as _random
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable, Iterable, Optional, Union

from activegraph.behaviors.base import Behavior, LLMBehavior, RelationBehavior
from activegraph.behaviors.decorators import get_registry
from activegraph.core.event import Event
from activegraph.core.graph import Graph, evaluate_where as _evaluate_where
from activegraph.core.ids import IDGen
from activegraph.core.view import View
from activegraph.frame import Frame
from activegraph.llm.cache import LLMCache
from activegraph.llm.errors import LLMBehaviorError, MissingProviderError
from activegraph.llm.provider import LLMProvider
from activegraph.llm.types import LLMMessage, ToolCall
from activegraph.policy import Policy
from activegraph.runtime.behavior_graph import BehaviorGraph
from activegraph.runtime.budget import Budget
from activegraph.runtime.diff import Diff, compute_diff
from activegraph.runtime.errors import ReplayDivergenceError
from activegraph.runtime.queue import EventQueue
from activegraph.runtime.registry import Registry
from activegraph.runtime.scheduler import DelayedQueue, ScheduledEntry
from activegraph.runtime.view_builder import build_view
from activegraph.tools.base import Tool
from activegraph.tools.cache import (
    CachedToolResponse,
    canonicalize_args,
    hash_tool_call,
)
from activegraph.tools.context import ToolContext
from activegraph.tools.decorators import get_tool_registry
from activegraph.tools.errors import (
    MissingToolError,
    ToolError,
    UnknownToolError,
)
from activegraph.tools.recorded import DirectToolInvoker


@dataclass
class Context:
    view: View
    frame: Optional[Frame]
    policy: Optional[Policy]
    random: _random.Random
    clock: Any  # Clock-like
    llm_provider: Optional[LLMProvider] = None
    # v0.7: pattern bindings for the current invocation. Empty list for
    # behaviors that don't declare a pattern. The handler is fired
    # ONCE per event regardless of how many bindings the pattern
    # produced — iterating `ctx.matches` is the developer's job
    # (CONTRACT v0.7 #12).
    matches: list = field(default_factory=list)


class Runtime:
    def __init__(
        self,
        graph: Graph,
        behaviors: Optional[Iterable[Union[Behavior, RelationBehavior]]] = None,
        frame: Optional[Frame] = None,
        policy: Optional[Policy] = None,
        budget: Optional[dict[str, Any]] = None,
        seed: int = 0,
        *,
        persist_to: Optional[str] = None,
        store: Optional[Any] = None,
        replay_strict: bool = False,
        llm_provider: Optional[LLMProvider] = None,
        replay_llm_cache: bool = False,
        llm_cache: Optional[LLMCache] = None,
        # v0.7 additions
        tools: Optional[Iterable[Tool]] = None,
        replay_tool_cache: bool = False,
        tool_cache: Any = None,  # ToolCache; Any to avoid import cycle
        replay_reinvoke_deterministic: bool = False,
        tool_invoker: Any = None,  # defaults to DirectToolInvoker()
    ) -> None:
        self.graph = graph
        self.frame = frame
        self.policy = policy
        self.budget = Budget(budget or {})
        self._random = _random.Random(seed)
        self.replay_strict = replay_strict
        # CONTRACT v0.6 #3: provider is set once at construction.
        self.llm_provider: Optional[LLMProvider] = llm_provider
        self.replay_llm_cache: bool = replay_llm_cache
        # Cache is content-keyed by prompt hash. May be pre-populated
        # (load/fork with replay_llm_cache=True) or lazily filled.
        self._llm_cache: Optional[LLMCache] = llm_cache
        # During _verify_replay we install the sequence of expected
        # prompt hashes (from recorded llm.requested events). A live
        # re-assembled prompt whose hash doesn't match the next
        # expected one is a divergence — pinned to the new
        # llm.requested event id (decision-2 adjustment).
        self._strict_expected_hashes: Optional[list[str]] = None

        # v0.7: tool plumbing
        self._explicit_tools = list(tools) if tools is not None else None
        self.tool_registry: dict[str, Tool] = {}
        self.replay_tool_cache: bool = replay_tool_cache
        from activegraph.tools.cache import ToolCache as _ToolCache
        self._tool_cache = tool_cache if tool_cache is not None else _ToolCache()
        self.replay_reinvoke_deterministic: bool = replay_reinvoke_deterministic
        self._tool_invoker = tool_invoker if tool_invoker is not None else DirectToolInvoker()

        # If behaviors are passed explicitly, snapshot now. Otherwise, defer
        # to the global registry — the user may decorate behaviors after
        # constructing the Runtime (the README quickstart does exactly this).
        self._explicit_behaviors = (
            list(behaviors) if behaviors is not None else None
        )
        self.registry: Optional[Registry] = None

        # frame id (cheap auto-allocate so provenance always has one)
        if self.frame is not None and self.frame.id is None:
            self.frame.id = graph.ids.frame()

        self._queue = EventQueue()
        # v0.7: delayed queue for activate_after scheduling.
        self._delayed = DelayedQueue()
        # Event tick counter: increments for every non-lifecycle event
        # processed. This is the time axis for activate_after.
        self._tick: int = 0
        # Stash for tool result message between _invoke_tool and the
        # turn-loop caller. Always cleared after consumption.
        self._last_tool_result_message: Optional[LLMMessage] = None
        self._inside_dispatch = False
        graph.add_listener(self._on_event)
        self._idle_emitted = False

        # ---- v0.5: persistence wiring ----
        if persist_to is not None and store is not None:
            raise ValueError("pass either persist_to or store, not both")
        if persist_to is not None:
            store = _open_sqlite_store(persist_to, graph.run_id)
            store.upsert_run(
                created_at=_now_iso(),
                frame_id=self.frame.id if self.frame else None,
            )
        if store is not None:
            graph.attach_store(store)

    # ---------- public surface ----------

    @property
    def run_id(self) -> str:
        return self.graph.run_id

    # ---------- listener ----------

    def _on_event(self, event: Event) -> None:
        # Don't enqueue our own lifecycle events for re-matching.
        # v0.7 adds `llm.*`, `tool.*`, `pattern.*`, `behavior.scheduled`
        # to the suppression list — they're internal to the runtime's
        # bookkeeping. (User behaviors that want to audit LLM/tool
        # activity can still subscribe via the registry's lookup.)
        if (
            event.type.startswith("behavior.")
            or event.type.startswith("relation_behavior.")
            or event.type.startswith("runtime.")
            or event.type.startswith("llm.")
            or event.type.startswith("tool.")
            or event.type.startswith("pattern.")
        ):
            return
        self._queue.push(event)
        # New activity → we're not idle anymore.
        self._idle_emitted = False

    # ---------- public entry points ----------

    def _ensure_registry(self) -> None:
        source = (
            self._explicit_behaviors
            if self._explicit_behaviors is not None
            else get_registry()
        )
        # CONTRACT v0.6 #21: LLM behaviors fail loud at registration if
        # there is no provider. We do not silently fall back to a mock —
        # a missing provider is almost always a real misconfiguration.
        if self.llm_provider is None:
            for b in source:
                if isinstance(b, LLMBehavior):
                    raise MissingProviderError(
                        f"behavior {b.name!r} is an @llm_behavior but the "
                        f"runtime has no llm_provider. Pass "
                        f"`Runtime(graph, llm_provider=...)`."
                    )
        self.registry = Registry(source)

        # v0.7: assemble the tool registry. Explicit tools= override the
        # global @tool registry, mirroring how behaviors= works.
        if self._explicit_tools is not None:
            tools_source = self._explicit_tools
        else:
            tools_source = get_tool_registry()
        # LLM behaviors may also bring their own tools via tools=[...] on
        # the decorator; pull those in too so the name lookup is unified.
        for b in source:
            if isinstance(b, LLMBehavior):
                for t in b.tools:
                    if isinstance(t, Tool) and t not in tools_source:
                        tools_source = list(tools_source) + [t]
        # CONTRACT v0.7 #2: each LLM behavior with tools= must reference
        # registered tools by Tool object or by name string. Names are
        # resolved against the merged registry. Missing → MissingToolError.
        self.tool_registry = {}
        for t in tools_source:
            if not isinstance(t, Tool):
                raise TypeError(
                    f"tool {t!r} is not a Tool instance "
                    f"(decorate with @tool or pass a Tool object)"
                )
            self.tool_registry[t.name] = t
        for b in source:
            if not isinstance(b, LLMBehavior):
                continue
            for t in b.tools:
                name = t.name if isinstance(t, Tool) else str(t)
                if name not in self.tool_registry:
                    raise MissingToolError(
                        f"behavior {b.name!r} declares tool {name!r} but it "
                        f"is not registered (register with @tool or pass via "
                        f"Runtime(tools=[...]))"
                    )

    def run_goal(self, goal: str, *, actor: str = "user") -> None:
        self._ensure_registry()
        # Stamp the run row's goal (best-effort; only meaningful with a store).
        if self.graph.store is not None and hasattr(self.graph.store, "upsert_run"):
            self.graph.store.upsert_run(
                created_at=_now_iso(),
                goal=goal,
                frame_id=self.frame.id if self.frame else None,
            )
        ev = Event(
            id=self.graph.ids.event(),
            type="goal.created",
            payload={"goal": goal},
            actor=actor,
            frame_id=self.frame.id if self.frame else None,
            caused_by=None,
            timestamp=self.graph.clock.now(),
        )
        self.budget.start()
        self.graph.emit(ev)
        self.run_until_idle()

    def run_until_idle(self) -> None:
        self._ensure_registry()
        if self.budget._start is None:
            self.budget.start()
        self._loop(stop=lambda: False)
        self._emit_idle_or_exhausted()

    def run_until(self, predicate: Callable[[Graph], bool]) -> None:
        self._ensure_registry()
        if self.budget._start is None:
            self.budget.start()
        self._loop(stop=lambda: predicate(self.graph))
        self._emit_idle_or_exhausted()

    # ---------- loop ----------

    def _loop(self, *, stop: Callable[[], bool]) -> None:
        while (self._queue or self._delayed) and self.budget.remaining():
            if stop():
                return
            # Always drain main queue first. Delayed entries are checked
            # after each event tick so they fire at the right moment.
            if self._queue:
                event = self._queue.pop()
                assert event is not None
                self.budget.consume("max_events")
                self._tick += 1
                matches = self.registry.match(event, self.graph)
                for b, rels, p_matches in matches:
                    if not self.budget.remaining():
                        break
                    # v0.7: activate_after defers invocation. Schedule and
                    # emit `behavior.scheduled` instead of invoking now.
                    if b.activate_after is not None:
                        self._schedule(b, event, p_matches)
                        continue
                    if p_matches and (b.on and b.pattern):
                        self._emit_pattern_matched(b, event, p_matches)
                    elif p_matches and not b.on:
                        # Pattern-only behavior: still emit a marker so
                        # the trace shows what fired.
                        self._emit_pattern_matched(b, event, p_matches)
                    if isinstance(b, RelationBehavior):
                        for r in rels:
                            if not self.budget.remaining():
                                break
                            self._invoke_relation(b, r, event, p_matches)
                    elif isinstance(b, LLMBehavior):
                        self._invoke_llm(b, event, p_matches)
                    else:
                        self._invoke(b, event, p_matches)
            # Drain due delayed entries (after every tick).
            self._fire_due_delayed()

    # ---- v0.7: delayed-queue scheduling (activate_after) -----------------

    def _schedule(
        self,
        behavior,
        event: Event,
        pattern_matches,
    ) -> None:
        """Emit behavior.scheduled and push onto the delayed queue."""
        sched_evt = self._emit_lifecycle(
            "behavior.scheduled",
            {
                "behavior": behavior.name,
                "event_id": event.id,
                "activate_after": behavior.activate_after,
                "fire_at_tick": self._tick + behavior.activate_after,
                "current_tick": self._tick,
            },
        )
        self._delayed.push(
            ScheduledEntry(
                behavior_name=behavior.name,
                behavior_index=self.registry.index_of(behavior),
                triggering_event_id=event.id,
                fire_at_event_count=self._tick + behavior.activate_after,
                where_recheck_path=None,
                scheduled_event_id=sched_evt.id,
            )
        )

    def _fire_due_delayed(self) -> None:
        due = self._delayed.pop_due(self._tick)
        for entry in due:
            if not self.budget.remaining():
                # Re-push and exit — budget exhausted before all due
                # entries fired; preserved for next run_until_idle.
                self._delayed.push(entry)
                break
            behavior = self.registry.all()[entry.behavior_index]
            # Re-fetch the triggering event so the handler still sees it.
            ev = self._find_event(entry.triggering_event_id)
            if ev is None:
                continue
            # Re-check where= against the LATEST graph state.
            if behavior.where and not _evaluate_where(behavior.where, ev.payload):
                # Silently skip per CONTRACT v0.7 #13. The trace already
                # has the behavior.scheduled event; absence of a
                # behavior.started is sufficient evidence the where
                # didn't hold.
                continue
            # Re-check pattern as well so a stale pattern hit doesn't
            # fire after the graph has moved on. We pass empty matches
            # if there's no pattern.
            p_matches: list = []
            if behavior.pattern_matcher is not None:
                p_matches = behavior.pattern_matcher.matches(ev, self.graph)
                if not p_matches:
                    continue
            # Dispatch as normal (without re-scheduling — we are AT the
            # fire moment).
            if isinstance(behavior, RelationBehavior):
                # For relation behaviors we'd need to refetch relations.
                # Defer this rare combination to a future enhancement.
                continue
            if isinstance(behavior, LLMBehavior):
                self._invoke_llm(behavior, ev, p_matches)
            else:
                self._invoke(behavior, ev, p_matches)

    def _find_event(self, event_id: str) -> Optional[Event]:
        for e in self.graph.events:
            if e.id == event_id:
                return e
        return None

    def _emit_pattern_matched(self, behavior, event: Event, p_matches) -> None:
        """Emit a pattern.matched marker so the trace shows the bindings."""
        self._emit_lifecycle(
            "pattern.matched",
            {
                "behavior": behavior.name,
                "event_id": event.id,
                "matches_count": len(p_matches),
                "pattern": behavior.pattern,
            },
        )

    # ---------- invocation ----------

    def _invoke(self, b: Behavior, event: Event, matches: Optional[list] = None) -> None:
        self.budget.consume("max_behavior_calls")
        bgraph = BehaviorGraph(
            self.graph,
            actor=b.name,
            caused_by=event.id,
            frame_id=self.frame.id if self.frame else None,
        )
        view = build_view(b, event, self.graph)
        ctx = Context(
            view=view,
            frame=self.frame,
            policy=self.policy,
            random=self._random,
            clock=self.graph.clock,
            matches=list(matches or []),
        )

        self._emit_lifecycle(
            "behavior.started",
            {
                "behavior": b.name,
                "event_id": event.id,
                "triggering_event_type": event.type,
                "triggering_object_id": _maybe_object_id(event),
            },
        )
        try:
            b.run(event, bgraph, ctx)
        except Exception as e:
            self._emit_lifecycle(
                "behavior.failed",
                {
                    "behavior": b.name,
                    "event_id": event.id,
                    "exception_type": type(e).__name__,
                    "message": str(e),
                    "traceback": traceback.format_exc(),
                },
            )
            return

        self._emit_lifecycle(
            "behavior.completed",
            {
                "behavior": b.name,
                "event_id": event.id,
                "objects_created": bgraph.counters.objects_created,
                "relations_created": bgraph.counters.relations_created,
                "patches_applied": bgraph.counters.patches_applied,
                "patches_proposed": bgraph.counters.patches_proposed,
                "events_emitted": bgraph.counters.events_emitted,
            },
        )

    def _invoke_llm(
        self,
        b: LLMBehavior,
        event: Event,
        matches: Optional[list] = None,
    ) -> None:
        """LLM behavior lifecycle, v0.7 — turn loop over tool calls.

        Order:
          behavior.started
            (loop, up to max_tool_turns):
              assemble prompt   (with tools= if b.tools)
              cache lookup      (LLM cache)
              optional cost gate (if max_cost_usd)
              emit llm.requested
              provider.complete() | cached
              emit llm.responded
              if response.tool_calls: dispatch each tool, append result
                                       to messages, loop again
              else: break with response.parsed
            handler(event, bgraph, ctx, parsed)
          behavior.completed
        """

        self.budget.consume("max_behavior_calls")
        self.budget.consume("max_llm_calls")

        view = build_view(b, event, self.graph)
        bgraph = BehaviorGraph(
            self.graph,
            actor=b.name,
            caused_by=event.id,
            frame_id=self.frame.id if self.frame else None,
        )
        ctx = Context(
            view=view,
            frame=self.frame,
            policy=self.policy,
            random=self._random,
            clock=self.graph.clock,
            llm_provider=self.llm_provider,
            matches=list(matches or []),
        )

        self._emit_lifecycle(
            "behavior.started",
            {
                "behavior": b.name,
                "event_id": event.id,
                "triggering_event_type": event.type,
                "triggering_object_id": _maybe_object_id(event),
            },
        )

        # v0.7: resolve tool objects (decorator may have stored names or
        # objects). Build the provider-facing tool definitions list.
        tools_for_call: list[Tool] = []
        for t in b.tools:
            name = t.name if isinstance(t, Tool) else str(t)
            tool_obj = self.tool_registry.get(name)
            if tool_obj is None:
                self._emit_behavior_failed(
                    b.name,
                    event.id,
                    MissingToolError(f"unregistered tool: {name}"),
                    reason="tool.unknown_tool",
                    extras={"tool": name},
                )
                return
            tools_for_call.append(tool_obj)
        tool_defs = [t.to_definition() for t in tools_for_call] if tools_for_call else None
        tool_request_event_ids: list[str] = []

        # ---- 1. Assemble base prompt -------------------------------------
        try:
            prompt = b.build_prompt(event, self.graph, frame=self.frame)
        except Exception as e:  # pragma: no cover — defensive
            self._emit_behavior_failed(
                b.name,
                event.id,
                e,
                reason="llm.prompt_assembly_error",
            )
            return

        # The base prompt has the system text + a single user message
        # assembled from view+event+instruction. The turn loop will
        # append assistant/tool messages as it goes.
        running_messages: list[LLMMessage] = list(prompt.messages)

        # The "last LLM request event id" gets stamped onto every
        # object/relation/patch the handler creates. We track the
        # most recent one — across the turn loop it's always the
        # FINAL llm.requested whose response actually fed the handler.
        last_llm_request_id: Optional[str] = None
        first_llm_request_id: Optional[str] = None
        response = None  # final non-tool response

        for turn_idx in range(max(1, b.max_tool_turns)):
            if not self.budget.remaining():
                self._emit_behavior_failed(
                    b.name,
                    event.id,
                    RuntimeError("budget exhausted mid-turn-loop"),
                    reason=_budget_reason(self.budget.exhausted_by()),
                )
                return
            turn_hash = _hash_turn_prompt(
                prompt=prompt,
                messages=running_messages,
                tool_defs=tool_defs,
            )

            # ---- Cache lookup ----------------------------------------------
            cached: Optional[Any] = None
            if self.replay_llm_cache and self._llm_cache is not None:
                cached = self._llm_cache.get(turn_hash)

            # ---- Pre-call cost gate ----------------------------------------
            pre_estimate_cost: Optional[Decimal] = None
            estimated_input_tokens: Optional[int] = None
            if cached is None and self.budget.has_cost_limit():
                try:
                    estimated_input_tokens = self.llm_provider.count_tokens(
                        system=prompt.system,
                        messages=running_messages,
                        model=prompt.model,
                    )
                except Exception as e:
                    self._emit_behavior_failed(
                        b.name,
                        event.id,
                        e,
                        reason="llm.network_error",
                        extras={"model": prompt.model, "phase": "count_tokens"},
                    )
                    return
                pre_estimate_cost = self.llm_provider.estimate_cost(
                    input_tokens=estimated_input_tokens,
                    output_tokens=prompt.max_tokens,
                    model=prompt.model,
                )
                if not self.budget.cost_remaining(pre_estimate_cost):
                    self._emit_behavior_failed(
                        b.name,
                        event.id,
                        RuntimeError("max_cost_usd would be exceeded"),
                        reason="budget.cost_exhausted",
                        extras={
                            "estimated_cost_usd": str(pre_estimate_cost),
                            "budget_remaining_usd": str(
                                self.budget.cost_remaining_amount()
                            ),
                            "model": prompt.model,
                        },
                    )
                    return

            # ---- Emit llm.requested ----------------------------------------
            requested_payload: dict[str, Any] = {
                "behavior": b.name,
                "model": prompt.model,
                "prompt_hash": turn_hash,
                "deterministic": prompt.deterministic,
                "cache_hit": cached is not None,
                "turn_index": turn_idx,
                # CONTRACT v0.6 follow-up: surface the prompt-normalized
                # flag explicitly so trace consumers can see that
                # volatile-field stripping ran (always true in v0.7).
                "prompt_normalized": True,
            }
            if turn_idx == 0:
                # Only include full prompt body on turn 0; subsequent
                # turns can be reconstructed from messages.
                requested_payload["prompt"] = prompt.to_hashable()
            if estimated_input_tokens is not None:
                requested_payload["estimated_input_tokens"] = estimated_input_tokens
            if pre_estimate_cost is not None:
                requested_payload["estimated_cost_usd"] = str(pre_estimate_cost)
            if self.budget.has_cost_limit():
                remaining = self.budget.cost_remaining_amount()
                requested_payload["budget_remaining_usd"] = (
                    str(remaining) if remaining is not None else None
                )
            requested_evt = self._emit_llm_event(
                "llm.requested",
                requested_payload,
                actor=b.name,
                caused_by=event.id if turn_idx == 0 else last_llm_request_id,
            )
            if first_llm_request_id is None:
                first_llm_request_id = requested_evt.id
            last_llm_request_id = requested_evt.id

            # ---- Strict-replay hash check ---------------------------------
            if self.replay_strict and self._strict_expected_hashes is not None:
                expected = (
                    self._strict_expected_hashes.pop(0)
                    if self._strict_expected_hashes
                    else None
                )
                if expected is not None and expected != turn_hash:
                    raise ReplayDivergenceError(
                        event_id=requested_evt.id,
                        expected=f"prompt_hash={expected}",
                        actual=f"prompt_hash={turn_hash}",
                    )

            # ---- Get the response (cache or provider) ---------------------
            if cached is not None:
                turn_response = cached
            else:
                try:
                    turn_response = self.llm_provider.complete(
                        system=prompt.system,
                        messages=running_messages,
                        model=prompt.model,
                        max_tokens=prompt.max_tokens,
                        temperature=prompt.temperature,
                        top_p=prompt.top_p,
                        output_schema=b.output_schema,
                        timeout_seconds=b.timeout_seconds,
                        tools=tool_defs,
                    )
                except LLMBehaviorError as e:
                    self._emit_behavior_failed(
                        b.name, event.id, e, reason=e.reason,
                        extras=e.payload_extras,
                    )
                    return
                except Exception as e:
                    self._emit_behavior_failed(
                        b.name, event.id, e,
                        reason="llm.network_error",
                        extras={"model": prompt.model},
                    )
                    return
                self._llm_cache.record(
                    turn_hash, turn_response, requesting_event_id=requested_evt.id
                ) if self._llm_cache is not None else None
                if self._llm_cache is None:
                    self._llm_cache = LLMCache()
                    self._llm_cache.record(
                        turn_hash, turn_response, requesting_event_id=requested_evt.id
                    )
                self.budget.add_cost(turn_response.cost_usd)

            # ---- Emit llm.responded ---------------------------------------
            responded_payload = turn_response.to_dict() | {
                "behavior": b.name,
                "prompt_hash": turn_hash,
                "turn_index": turn_idx,
            }
            self._emit_llm_event(
                "llm.responded",
                responded_payload,
                actor=b.name,
                caused_by=requested_evt.id,
            )

            # ---- Branch: tool calls vs final response ---------------------
            # `tool_calls` is optional on LLMResponse; some test providers
            # return ad-hoc objects without it. Treat missing/None/empty
            # as "no tool calls" so backward compatibility holds.
            response_tool_calls = getattr(turn_response, "tool_calls", None) or []
            if not response_tool_calls:
                response = turn_response
                break

            # Tool calls. Append the assistant turn to messages, then
            # dispatch each tool. Anthropic's assistant turn that
            # triggers tool_use carries the model's reasoning text plus
            # the tool_use blocks; we approximate by including raw_text
            # (may be empty) — the providers' adapters handle the rest.
            if turn_response.raw_text:
                running_messages.append(
                    LLMMessage(role="assistant", content=turn_response.raw_text)
                )
            for call in response_tool_calls:
                # CONTRACT v0.7 #6: budget enforcement BEFORE invocation
                # so an exhausted budget fails the behavior, doesn't
                # silently no-op. Check the tool-call counter FIRST so
                # we surface the specific v0.7 reason code rather than
                # the generic budget name.
                limit = self.budget.limits.get("max_tool_calls", float("inf"))
                if self.budget.used.get("max_tool_calls", 0.0) >= limit:
                    self._emit_behavior_failed(
                        b.name, event.id,
                        RuntimeError("max_tool_calls exhausted"),
                        reason="budget.tool_calls_exhausted",
                        extras={"tool": call.name},
                    )
                    return
                if not self.budget.remaining():
                    self._emit_behavior_failed(
                        b.name, event.id,
                        RuntimeError("budget exhausted before tool call"),
                        reason=_budget_reason(self.budget.exhausted_by()),
                        extras={"tool": call.name},
                    )
                    return
                # Tool must have been declared by the behavior.
                if not any(
                    (isinstance(t, Tool) and t.name == call.name)
                    or (isinstance(t, str) and t == call.name)
                    for t in b.tools
                ):
                    self._emit_behavior_failed(
                        b.name, event.id,
                        UnknownToolError(
                            f"LLM called tool {call.name!r} which is not "
                            f"declared on @llm_behavior(tools=[...])"
                        ),
                        reason="tool.unknown_tool",
                        extras={"tool": call.name},
                    )
                    return
                tool_obj = self.tool_registry[call.name]
                tr_id = self._invoke_tool(
                    behavior=b,
                    event=event,
                    tool=tool_obj,
                    call=call,
                    last_llm_request_id=requested_evt.id,
                    ctx_frame=self.frame,
                )
                if tr_id is None:
                    # tool failed — wrapper already emitted behavior.failed.
                    return
                tool_request_event_ids.append(tr_id)
                # Append tool result back into the conversation so the
                # next turn sees it. The result message was stashed by
                # _invoke_tool on self._last_tool_result_message.
                if self._last_tool_result_message is not None:
                    running_messages.append(self._last_tool_result_message)
                    self._last_tool_result_message = None

            # All tool calls succeeded; loop again with new messages.
            continue
        else:
            # for/else: we ran out of turns without a final response.
            self._emit_behavior_failed(
                b.name,
                event.id,
                RuntimeError(
                    f"exceeded max_tool_turns={b.max_tool_turns} without "
                    f"a non-tool response"
                ),
                reason="tool.max_turns_exhausted",
                extras={"max_tool_turns": b.max_tool_turns},
            )
            return

        # ---- Hydrate parsed output (cache may have dicts) -----------------
        if (
            b.output_schema is not None
            and response.parsed is not None
            and not isinstance(response.parsed, b.output_schema)
        ):
            try:
                response.parsed = b.output_schema.model_validate(response.parsed)
            except Exception as e:
                self._emit_behavior_failed(
                    b.name,
                    event.id,
                    e,
                    reason="llm.schema_violation",
                    extras={
                        "raw_text": response.raw_text,
                        "schema": b.output_schema.__name__,
                        "validation_errors": str(e),
                        "from_cache": True,
                    },
                )
                return

        # ---- Validate output ---------------------------------------------
        if b.output_schema is not None and response.parsed is None:
            self._emit_behavior_failed(
                b.name,
                event.id,
                LLMBehaviorError(
                    "llm.parse_error",
                    "provider returned no parsed output despite output_schema",
                ),
                reason="llm.parse_error",
                extras={
                    "raw_text": response.raw_text,
                    "schema": b.output_schema.__name__,
                },
            )
            return

        # ---- Invoke developer handler with provenance stamping -----------
        bgraph._llm_request_event_id = first_llm_request_id  # noqa: SLF001
        bgraph._tool_request_event_ids = list(tool_request_event_ids)  # noqa: SLF001
        try:
            b.handler(event, bgraph, ctx, response.parsed)
        except LLMBehaviorError as e:
            self._emit_behavior_failed(
                b.name, event.id, e, reason=e.reason,
                extras=e.payload_extras,
            )
            return
        except Exception as e:
            self._emit_behavior_failed(b.name, event.id, e)
            return

        self._emit_lifecycle(
            "behavior.completed",
            {
                "behavior": b.name,
                "event_id": event.id,
                "objects_created": bgraph.counters.objects_created,
                "relations_created": bgraph.counters.relations_created,
                "patches_applied": bgraph.counters.patches_applied,
                "patches_proposed": bgraph.counters.patches_proposed,
                "events_emitted": bgraph.counters.events_emitted,
                "tool_calls": len(tool_request_event_ids),
            },
        )

    # ---- v0.7: single tool invocation ------------------------------------

    def _invoke_tool(
        self,
        *,
        behavior: LLMBehavior,
        event: Event,
        tool: Tool,
        call: ToolCall,
        last_llm_request_id: str,
        ctx_frame: Optional[Frame],
    ) -> Optional[str]:
        """Dispatch a single tool call. Emits tool.requested + tool.responded.

        Returns the `tool.requested` event id on success; None on
        failure (caller has already emitted behavior.failed).
        """
        import logging
        import uuid

        self.budget.consume("max_tool_calls")
        args_hash = hash_tool_call(tool_name=tool.name, args=call.args)

        # Validate input
        try:
            if tool.input_schema is not None:
                input_obj = tool.input_schema.model_validate(call.args)
            else:
                input_obj = call.args
        except Exception as e:
            # Emit a tool.requested + tool.responded(error=...) pair
            # before bubbling the failure, so the trace is complete.
            req_evt = self._emit_tool_event(
                "tool.requested",
                {
                    "behavior": behavior.name,
                    "tool": tool.name,
                    "args_hash": args_hash,
                    "args": canonicalize_args(call.args),
                    "call_id": call.id,
                    "cache_hit": False,
                },
                actor=behavior.name,
                caused_by=last_llm_request_id,
            )
            err = {"reason": "tool.invalid_input", "message": str(e)}
            self._emit_tool_event(
                "tool.responded",
                {
                    "behavior": behavior.name,
                    "tool": tool.name,
                    "args_hash": args_hash,
                    "error": err,
                    "cache_hit": False,
                    "latency_seconds": 0.0,
                    "cost_usd": "0",
                },
                actor=behavior.name,
                caused_by=req_evt.id,
            )
            self._emit_behavior_failed(
                behavior.name, event.id, e,
                reason="tool.invalid_input",
                extras={"tool": tool.name, "validation_errors": str(e)},
            )
            return None

        # Cache lookup
        cached_tool: Optional[CachedToolResponse] = None
        if self.replay_tool_cache:
            cached_tool = self._tool_cache.get(args_hash)
            # Determinism opt-in: re-invoke deterministic tools instead
            # of serving from cache.
            if cached_tool is not None and tool.deterministic and self.replay_reinvoke_deterministic:
                cached_tool = None

        # Cost gate (tools and LLM share max_cost_usd budget)
        if cached_tool is None and self.budget.has_cost_limit():
            if not self.budget.cost_remaining(tool.cost_per_call):
                self._emit_behavior_failed(
                    behavior.name, event.id,
                    RuntimeError("max_cost_usd would be exceeded by tool"),
                    reason="budget.cost_exhausted",
                    extras={
                        "tool": tool.name,
                        "estimated_cost_usd": str(tool.cost_per_call),
                    },
                )
                return None

        # Emit tool.requested
        req_evt = self._emit_tool_event(
            "tool.requested",
            {
                "behavior": behavior.name,
                "tool": tool.name,
                "args_hash": args_hash,
                "args": canonicalize_args(call.args),
                "call_id": call.id,
                "cache_hit": cached_tool is not None,
                "deterministic": tool.deterministic,
            },
            actor=behavior.name,
            caused_by=last_llm_request_id,
        )

        if cached_tool is not None:
            tool_response = cached_tool
        else:
            tool_ctx = ToolContext(
                behavior_name=behavior.name,
                event_id=event.id,
                frame=ctx_frame,
                idempotency_key=str(uuid.uuid4()),
                timeout_seconds=tool.timeout_seconds,
                logger=logging.getLogger(f"activegraph.tools.{tool.name}"),
            )
            try:
                tool_response = self._tool_invoker.invoke(tool, input_obj, tool_ctx)
            except ToolError as e:
                self._emit_tool_event(
                    "tool.responded",
                    {
                        "behavior": behavior.name,
                        "tool": tool.name,
                        "args_hash": args_hash,
                        "error": {
                            "reason": e.reason,
                            "message": str(e),
                            **e.payload_extras,
                        },
                        "cache_hit": False,
                        "latency_seconds": 0.0,
                        "cost_usd": "0",
                    },
                    actor=behavior.name,
                    caused_by=req_evt.id,
                )
                self._emit_behavior_failed(
                    behavior.name, event.id, e,
                    reason=e.reason,
                    extras={"tool": tool.name, **e.payload_extras},
                )
                return None
            self._tool_cache.record(
                args_hash, tool_response, requesting_event_id=req_evt.id
            )
            self.budget.add_cost(tool_response.cost_usd)

        # Validate output (if schema)
        validated_output = tool_response.output
        if tool.output_schema is not None and tool_response.output is not None:
            try:
                model_inst = tool.output_schema.model_validate(tool_response.output)
                dump = getattr(model_inst, "model_dump", None)
                if callable(dump):
                    try:
                        validated_output = dump(mode="json")
                    except TypeError:
                        validated_output = dump()
            except Exception as e:
                self._emit_tool_event(
                    "tool.responded",
                    {
                        "behavior": behavior.name,
                        "tool": tool.name,
                        "args_hash": args_hash,
                        "error": {
                            "reason": "tool.invalid_output",
                            "message": str(e),
                        },
                        "cache_hit": tool_response.cache_hit,
                        "latency_seconds": tool_response.latency_seconds,
                        "cost_usd": str(tool_response.cost_usd),
                    },
                    actor=behavior.name,
                    caused_by=req_evt.id,
                )
                self._emit_behavior_failed(
                    behavior.name, event.id, e,
                    reason="tool.invalid_output",
                    extras={
                        "tool": tool.name,
                        "validation_errors": str(e),
                    },
                )
                return None

        # Emit tool.responded
        self._emit_tool_event(
            "tool.responded",
            {
                "behavior": behavior.name,
                "tool": tool.name,
                "args_hash": args_hash,
                "output": validated_output,
                "error": None,
                "cache_hit": tool_response.cache_hit,
                "latency_seconds": tool_response.latency_seconds,
                "cost_usd": str(tool_response.cost_usd),
                "deterministic": tool.deterministic,
            },
            actor=behavior.name,
            caused_by=req_evt.id,
        )

        # Echo the tool result back into the message stream so the
        # next LLM turn can see it.
        import json as _json
        running_messages_append = getattr(self, "_current_running_messages", None)
        # NOTE: we use the caller's local running_messages via closure;
        # to avoid threading it through, the caller appends after this.
        # Stash the tool-result content on the request event payload
        # for now so the caller can fetch it. Simpler: return a payload.

        # We append in the caller — but we need to return the content
        # too. Refactor: pass running_messages by reference via mutating
        # method. Cleanest: do it here using a passed list.
        # (Inlined below by storing in self._last_tool_result_message.)
        self._last_tool_result_message = LLMMessage(
            role="tool",
            content=_json.dumps(validated_output, sort_keys=True, default=str),
            tool_use_id=call.id,
            tool_name=tool.name,
        )
        return req_evt.id

    def _emit_tool_event(
        self,
        type_: str,
        payload: dict[str, Any],
        *,
        actor: str,
        caused_by: Optional[str],
    ) -> Event:
        ev = Event(
            id=self.graph.ids.event(),
            type=type_,
            payload=payload,
            actor=actor,
            frame_id=self.frame.id if self.frame else None,
            caused_by=caused_by,
            timestamp=self.graph.clock.now(),
        )
        self.graph.emit(ev)
        return ev

    def _emit_llm_event(
        self,
        type_: str,
        payload: dict[str, Any],
        *,
        actor: str,
        caused_by: Optional[str],
    ) -> Event:
        ev = Event(
            id=self.graph.ids.event(),
            type=type_,
            payload=payload,
            actor=actor,
            frame_id=self.frame.id if self.frame else None,
            caused_by=caused_by,
            timestamp=self.graph.clock.now(),
        )
        self.graph.emit(ev)
        return ev

    def _emit_behavior_failed(
        self,
        behavior_name: str,
        event_id: str,
        exc: BaseException,
        *,
        reason: Optional[str] = None,
        extras: Optional[dict[str, Any]] = None,
    ) -> None:
        """Centralized behavior.failed emission. CONTRACT #13 plus
        v0.6 #11 (optional `reason` + LLM-specific extras).
        """

        tb_str = "".join(
            traceback.format_exception(type(exc), exc, exc.__traceback__)
        ) if exc.__traceback__ is not None else traceback.format_exc()
        payload: dict[str, Any] = {
            "behavior": behavior_name,
            "event_id": event_id,
            "exception_type": type(exc).__name__,
            "message": str(exc),
            "traceback": tb_str,
        }
        if reason is not None:
            payload["reason"] = reason
        if extras:
            for k, v in extras.items():
                if k not in payload:
                    payload[k] = v
        self._emit_lifecycle("behavior.failed", payload)

    def _invoke_relation(
        self,
        b: RelationBehavior,
        relation,
        event: Event,
        matches: Optional[list] = None,
    ) -> None:
        self.budget.consume("max_behavior_calls")
        bgraph = BehaviorGraph(
            self.graph,
            actor=b.name,
            caused_by=event.id,
            frame_id=self.frame.id if self.frame else None,
        )
        view = build_view(b, event, self.graph)
        ctx = Context(
            view=view,
            frame=self.frame,
            policy=self.policy,
            random=self._random,
            clock=self.graph.clock,
            matches=list(matches or []),
        )

        self._emit_lifecycle(
            "relation_behavior.started",
            {
                "behavior": b.name,
                "event_id": event.id,
                "triggering_event_type": event.type,
                "relation_type": b.relation_type,
                "relation_id": relation.id,
            },
        )
        try:
            b.run(relation, event, bgraph, ctx)
        except Exception as e:
            self._emit_lifecycle(
                "behavior.failed",
                {
                    "behavior": b.name,
                    "event_id": event.id,
                    "exception_type": type(e).__name__,
                    "message": str(e),
                    "traceback": traceback.format_exc(),
                },
            )
            return

        self._emit_lifecycle(
            "behavior.completed",
            {
                "behavior": b.name,
                "event_id": event.id,
                "objects_created": bgraph.counters.objects_created,
                "relations_created": bgraph.counters.relations_created,
                "patches_applied": bgraph.counters.patches_applied,
                "patches_proposed": bgraph.counters.patches_proposed,
                "events_emitted": bgraph.counters.events_emitted,
            },
        )

    # ---------- lifecycle / idle emit (bypass queue) ----------

    def _emit_lifecycle(self, type_: str, payload: dict[str, Any]) -> Event:
        ev = Event(
            id=self.graph.ids.event(),
            type=type_,
            payload=payload,
            actor="runtime",
            frame_id=self.frame.id if self.frame else None,
            caused_by=payload.get("event_id"),
            timestamp=self.graph.clock.now(),
        )
        self.graph.emit(ev)
        return ev

    def _emit_idle_or_exhausted(self) -> None:
        if self._idle_emitted:
            return
        if not self.budget.remaining():
            self._emit_lifecycle(
                "runtime.budget_exhausted",
                {
                    "exhausted_by": self.budget.exhausted_by(),
                    "snapshot": self.budget.snapshot(),
                },
            )
        else:
            self._emit_lifecycle(
                "runtime.idle",
                {"snapshot": self.budget.snapshot()},
            )
        self._idle_emitted = True

    # ---------- trace + graph dump (delegate to trace module) ----------

    @property
    def trace(self):
        from activegraph.trace.printer import Trace

        return Trace(self.graph)

    def print_trace(self) -> None:
        self.trace.print()

    def export_trace(self, path: str) -> None:
        with open(path, "w") as f:
            for ev in self.graph.events:
                f.write(json.dumps(ev.to_dict()) + "\n")

    def print_graph(self) -> None:
        print("graph:")
        print(f"  objects ({len(self.graph.all_objects())}):")
        for o in self.graph.all_objects():
            label = o.data.get("title") or o.data.get("text") or ""
            extra = f' "{label}"' if label else ""
            status = o.data.get("status")
            status_s = f" ({status})" if status else ""
            print(f"    {o.id}{extra}{status_s}")
        print(f"  relations ({len(self.graph.all_relations())}):")
        for r in self.graph.all_relations():
            print(f"    {r.source} --{r.type}--> {r.target}")

    # ---------- v0.5: save / load / fork / diff ----------

    def save_state(self, path: Optional[str] = None) -> str:
        """Persist the event log.

        - With a store already attached: flush (no path needed). If `path` is
          given it must match the attached store's path.
        - Without a store: late-bind a SQLite store at `path` and append all
          in-memory events to it (CONTRACT v0.5 #5).
        Returns the path the events were written to.
        """
        attached = self.graph.store
        if attached is not None:
            attached_path = getattr(attached, "path", None)
            if path is not None and attached_path is not None and path != attached_path:
                raise ValueError(
                    f"runtime already persisting to {attached_path!r}; cannot save to {path!r}"
                )
            # SQLite autocommit means already durable, but call commit() defensively.
            conn = getattr(attached, "_conn", None)
            if conn is not None:
                try:
                    conn.commit()
                except Exception:
                    pass
            return attached_path or "<in-memory>"

        if path is None:
            raise ValueError("save_state(path=...) required when no store is attached")

        store = _open_sqlite_store(path, self.graph.run_id)
        store.upsert_run(
            created_at=_now_iso(),
            goal=_first_goal(self.graph),
            frame_id=self.frame.id if self.frame else None,
        )
        # Append everything we've accumulated in memory.
        for ev in self.graph.events:
            store.append(ev)
        self.graph.attach_store(store)
        return path

    @classmethod
    def load(
        cls,
        path: str,
        run_id: Optional[str] = None,
        *,
        behaviors: Optional[Iterable[Union[Behavior, RelationBehavior]]] = None,
        frame: Optional[Frame] = None,
        policy: Optional[Policy] = None,
        budget: Optional[dict[str, Any]] = None,
        seed: int = 0,
        replay_strict: bool = False,
        llm_provider: Optional[LLMProvider] = None,
        replay_llm_cache: bool = False,
        tools: Optional[Iterable[Tool]] = None,
        replay_tool_cache: bool = False,
        replay_reinvoke_deterministic: bool = False,
    ) -> "Runtime":
        """Open `path`, choose a run, replay its events, return a Runtime
        wired to continue from where the log left off.

        If `run_id` is None, loads the most recently appended-to run
        (CONTRACT v0.5 #6).

        `replay_strict=True` re-fires behaviors from the recorded seed
        events and compares the resulting event-type stream (id, type) to
        the log. KNOWN LIMITATION (v0.5): payload-only drift is not
        detected; see CONTRACT v0.5 #7. Tightens in v0.6 with LLMs.
        """
        from activegraph.store.sqlite import SQLiteEventStore

        chosen = run_id or SQLiteEventStore.most_recent_run_id(path)
        if chosen is None:
            raise FileNotFoundError(f"no runs found in {path}")

        store = SQLiteEventStore(path, run_id=chosen)
        graph = Graph(ids=IDGen(), run_id=chosen)
        events = list(store.iter_events())
        for ev in events:
            graph._replay_event(ev)  # noqa: SLF001 — internal seam
        graph.ids.reseed_from_events(events)
        graph.attach_store(store)

        # If we're caching, harvest llm.responded events from the log so
        # forks and strict-replay re-runs serve from cache instead of
        # the API. Safe to construct even when there are no LLM events
        # (just an empty cache).
        cache = LLMCache.from_events(events) if replay_llm_cache else None
        # v0.7: same pattern for the tool cache.
        from activegraph.tools.cache import ToolCache as _ToolCache
        tcache = _ToolCache.from_events(events) if replay_tool_cache else None

        rt = cls(
            graph,
            behaviors=behaviors,
            frame=frame,
            policy=policy,
            budget=budget,
            seed=seed,
            replay_strict=replay_strict,
            llm_provider=llm_provider,
            replay_llm_cache=replay_llm_cache,
            llm_cache=cache,
            tools=tools,
            replay_tool_cache=replay_tool_cache,
            tool_cache=tcache,
            replay_reinvoke_deterministic=replay_reinvoke_deterministic,
        )
        # Make sure the run row exists (older files might predate it; in v0.5
        # they shouldn't, but be defensive).
        store.upsert_run(created_at=_now_iso())

        # Re-queue events whose behaviors never fired (CONTRACT v0.5 diff #8).
        # Events that already have a behavior.started referencing them are
        # left alone — re-firing them would duplicate work. Events that were
        # in the queue when the runtime stopped (e.g. budget exhausted) get
        # processed on the next run_until_idle / run_goal call. Behaviors
        # that started but never completed still lose their in-progress
        # work — that's the original tradeoff, unchanged.
        _requeue_unfired(rt, events)

        if replay_strict:
            _verify_replay(
                graph,
                events,
                behaviors,
                frame,
                policy,
                budget,
                seed,
                llm_provider=llm_provider,
            )

        return rt

    def fork(
        self,
        at_event: str,
        label: Optional[str] = None,
        *,
        behaviors: Optional[Iterable[Union[Behavior, RelationBehavior]]] = None,
        llm_provider: Optional[LLMProvider] = None,
        replay_llm_cache: bool = False,
        tools: Optional[Iterable[Tool]] = None,
        replay_tool_cache: bool = False,
        replay_reinvoke_deterministic: bool = False,
    ) -> "Runtime":
        """Branch this run at `at_event` into an independent new run.

        Requires a SQLite store. Copies events from the parent's log up to
        and including `at_event` into a fresh `run_id`, replays them into a
        new Graph, then returns a Runtime that operates on that Graph.
        Forks-of-forks work the same way (CONTRACT v0.5 #9).
        """
        from activegraph.store.sqlite import SQLiteEventStore

        store = self.graph.store
        if store is None or not isinstance(store, SQLiteEventStore):
            raise RuntimeError("fork requires a SQLite-backed runtime")

        new_run_id = self.graph.ids.run()
        SQLiteEventStore.fork_run(
            store.path,
            parent_run_id=self.graph.run_id,
            new_run_id=new_run_id,
            at_event_id=at_event,
            label=label,
            created_at=_now_iso(),
        )
        fork_store = SQLiteEventStore(store.path, run_id=new_run_id)
        fork_graph = Graph(ids=IDGen(), run_id=new_run_id)
        events = list(fork_store.iter_events())
        for ev in events:
            fork_graph._replay_event(ev)  # noqa: SLF001
        fork_graph.ids.reseed_from_events(events)
        fork_graph.attach_store(fork_store)

        # Reuse behaviors from the explicit list if the parent had one; else
        # let the new Runtime fall back to the global registry like v0 does.
        fork_behaviors = behaviors
        if fork_behaviors is None and self._explicit_behaviors is not None:
            fork_behaviors = list(self._explicit_behaviors)

        # Cache is populated from the PARENT's recorded llm.responded
        # events (not the fork's, which only contains events up to and
        # including at_event). A diverging fork that regenerates an
        # identical prompt will hit the cache; a divergent prompt will
        # fall through to the provider (CONTRACT v0.6 #8).
        cache = (
            LLMCache.from_events(self.graph.events) if replay_llm_cache else None
        )
        # v0.7: tool cache pre-populated from the parent's events.
        from activegraph.tools.cache import ToolCache as _ToolCache
        tcache = (
            _ToolCache.from_events(self.graph.events)
            if replay_tool_cache
            else None
        )

        rt = Runtime(
            fork_graph,
            behaviors=fork_behaviors,
            frame=self.frame,
            policy=self.policy,
            budget=None,  # fresh budget for the fork
            seed=0,
            llm_provider=llm_provider if llm_provider is not None else self.llm_provider,
            replay_llm_cache=replay_llm_cache,
            llm_cache=cache,
            tools=tools,
            replay_tool_cache=replay_tool_cache,
            tool_cache=tcache,
            replay_reinvoke_deterministic=replay_reinvoke_deterministic,
        )
        # CONTRACT v0.5 diff #8 (extended to fork in v0.6): events whose
        # behaviors never started get re-queued. For a fork at an early
        # event (e.g. goal.created) this is how downstream behaviors fire
        # on the fork — without it, fork-then-run-until-idle would be a
        # no-op when there's no new seed event.
        _requeue_unfired(rt, events)
        return rt

    def diff(self, other: "Runtime") -> Diff:
        return compute_diff(self.graph, other.graph, self.run_id, other.run_id)


# ---------- helpers ----------


_BUDGET_REASON_MAP = {
    "max_tool_calls": "budget.tool_calls_exhausted",
    "max_cost_usd": "budget.cost_exhausted",
    "max_llm_calls": "budget.llm_calls_exhausted",
}


def _budget_reason(name: Optional[str]) -> str:
    if name is None:
        return "budget.exhausted"
    return _BUDGET_REASON_MAP.get(name, f"budget.{name.removeprefix('max_')}_exhausted")


def _hash_turn_prompt(
    *,
    prompt,
    messages: list,
    tool_defs: Optional[list],
) -> str:
    """Hash the prompt+messages+tools for a single turn.

    Used as the LLM cache key per-turn (CONTRACT v0.7 per-turn cache
    decision). Includes the running messages list so each turn in a
    tool loop produces a distinct hash; same shape as v0.6's
    prompt.hash() otherwise.
    """
    import hashlib
    import json as _json

    payload = {
        "model": prompt.model,
        "system": prompt.system,
        "messages": [m.to_dict() for m in messages],
        "output_schema_name": prompt.output_schema_name,
        "output_schema_json": prompt.output_schema_json,
        "max_tokens": int(prompt.max_tokens),
        "temperature": float(prompt.temperature),
        "top_p": float(prompt.top_p),
        "deterministic": bool(prompt.deterministic),
        "tools": list(tool_defs) if tool_defs else None,
    }
    canonical = _json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _maybe_object_id(event: Event) -> Optional[str]:
    obj = event.payload.get("object") if isinstance(event.payload, dict) else None
    if isinstance(obj, dict):
        return obj.get("id")
    return None


def _now_iso() -> str:
    return (
        datetime.now(tz=timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _first_goal(graph: Graph) -> Optional[str]:
    for e in graph.events:
        if e.type == "goal.created":
            return e.payload.get("goal")
    return None


def _open_sqlite_store(path: str, run_id: str):
    from activegraph.store.sqlite import SQLiteEventStore

    return SQLiteEventStore(path, run_id=run_id)


def _requeue_unfired(rt: "Runtime", events: list[Event]) -> None:
    """Push events that haven't yet triggered any behavior back into the queue.

    See CONTRACT v0.5 diff #8 in CONTRACT.md for the rationale.

    INVARIANT (v0.5 only): under the single-threaded, run-to-completion loop
    (CONTRACT #10), an event has either been popped — in which case ALL
    matching behaviors have already had behavior.started emitted on it, or
    the runtime crashed before the loop could pop the next event. There is
    no partial-fanout state. So "no behavior.started ever referenced this
    event id" is equivalent to "this event was still in the queue when the
    runtime stopped". When v1 introduces parallelism (decision #16: out of
    scope for v0.5), this heuristic breaks — a fanout where 2 of 5 matched
    behaviors started before the crash would be re-queued, double-firing
    the 2 that did start. Revisit this function at the same time as the
    parallel-loop redesign.
    """
    fired_on: set[str] = set()
    for e in events:
        if (
            e.type.startswith("behavior.")
            or e.type.startswith("relation_behavior.")
        ):
            eid = e.payload.get("event_id") if isinstance(e.payload, dict) else None
            if eid:
                fired_on.add(eid)
    for e in events:
        if _is_lifecycle(e):
            continue
        if e.id in fired_on:
            continue
        rt._queue.push(e)  # noqa: SLF001 — internal seam by design
    if rt._queue:
        rt._idle_emitted = False


# ---------- replay strictness (CONTRACT v0.5 #7) ----------


def _verify_replay(
    loaded_graph: Graph,
    recorded_events: list[Event],
    behaviors: Optional[Iterable[Union[Behavior, RelationBehavior]]],
    frame: Optional[Frame],
    policy: Optional[Policy],
    budget: Optional[dict[str, Any]],
    seed: int,
    *,
    llm_provider: Optional[LLMProvider] = None,
) -> None:
    """Replay the run from scratch — fresh Graph, behaviors fire — and
    compare the resulting event stream to the recorded log.

    On the first mismatch (id or type), raise ReplayDivergenceError.

    CONTRACT v0.6: replay_strict implies cache-on for verification
    regardless of replay_llm_cache — otherwise we'd hit the live API.
    A live-rebuilt prompt whose hash doesn't match the recorded one is
    itself a divergence (decision-2 adjustment).
    """

    # Seed events: everything with no caused_by (goal.created, user-emitted
    # bootstrap events). Behaviors re-derive everything else.
    seed_events = [e for e in recorded_events if e.caused_by is None and not _is_lifecycle(e)]
    if not seed_events:
        return  # nothing to verify

    # Pre-populate the cache from recorded llm.responded events and
    # extract the sequence of expected prompt hashes (in the order the
    # behaviors fired them) so we can pin divergence at the right
    # event id.
    expected_hashes = [
        e.payload.get("prompt_hash")
        for e in recorded_events
        if e.type == "llm.requested" and e.payload.get("prompt_hash")
    ]
    cache = LLMCache.from_events(recorded_events)

    fresh = Graph(ids=IDGen(), run_id="verify_" + loaded_graph.run_id)
    fresh_rt = Runtime(
        fresh,
        behaviors=behaviors,
        frame=frame,
        policy=policy,
        budget=budget,
        seed=seed,
        llm_provider=llm_provider,
        replay_llm_cache=True,
        llm_cache=cache,
        replay_strict=True,
    )
    # Install the expected-hash queue. _invoke_llm pops one per LLM call
    # and raises ReplayDivergenceError if the live hash differs.
    fresh_rt._strict_expected_hashes = list(expected_hashes)
    fresh_rt._ensure_registry()

    # Replay seed events through emit so behaviors fire.
    for e in seed_events:
        new_id = fresh.ids.event()
        replay_ev = Event(
            id=new_id,
            type=e.type,
            payload=dict(e.payload),
            actor=e.actor,
            frame_id=e.frame_id,
            caused_by=None,
            timestamp=e.timestamp,
        )
        fresh.emit(replay_ev)
    fresh_rt.run_until_idle()

    # Compare type-stream of non-lifecycle events.
    rec_stream = [(e.id, e.type) for e in recorded_events if not _is_lifecycle(e)]
    new_stream = [(e.id, e.type) for e in fresh.events if not _is_lifecycle(e)]
    for i, (rec, new) in enumerate(zip(rec_stream, new_stream)):
        if rec[1] != new[1]:
            raise ReplayDivergenceError(
                event_id=rec[0], expected=rec[1], actual=new[1]
            )
    if len(rec_stream) != len(new_stream):
        # Length mismatch — pin the divergence point.
        offending = rec_stream[len(new_stream)][0] if len(new_stream) < len(rec_stream) else new_stream[len(rec_stream)][0]
        expected = rec_stream[len(new_stream)][1] if len(new_stream) < len(rec_stream) else "<no recorded event>"
        actual = new_stream[len(rec_stream)][1] if len(rec_stream) < len(new_stream) else None
        raise ReplayDivergenceError(event_id=offending, expected=expected, actual=actual)


def _is_lifecycle(e: Event) -> bool:
    return (
        e.type.startswith("behavior.")
        or e.type.startswith("relation_behavior.")
        or e.type.startswith("runtime.")
    )
