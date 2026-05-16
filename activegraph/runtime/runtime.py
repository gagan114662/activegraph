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
from activegraph.core.graph import Graph
from activegraph.core.ids import IDGen
from activegraph.core.view import View
from activegraph.frame import Frame
from activegraph.llm.cache import LLMCache
from activegraph.llm.errors import LLMBehaviorError, MissingProviderError
from activegraph.llm.provider import LLMProvider
from activegraph.policy import Policy
from activegraph.runtime.behavior_graph import BehaviorGraph
from activegraph.runtime.budget import Budget
from activegraph.runtime.diff import Diff, compute_diff
from activegraph.runtime.errors import ReplayDivergenceError
from activegraph.runtime.queue import EventQueue
from activegraph.runtime.registry import Registry
from activegraph.runtime.view_builder import build_view


@dataclass
class Context:
    view: View
    frame: Optional[Frame]
    policy: Optional[Policy]
    random: _random.Random
    clock: Any  # Clock-like
    llm_provider: Optional[LLMProvider] = None


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
        if event.type.startswith("behavior.") or event.type.startswith(
            "relation_behavior."
        ) or event.type.startswith("runtime."):
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
        while self._queue and self.budget.remaining():
            if stop():
                return
            event = self._queue.pop()
            assert event is not None
            self.budget.consume("max_events")
            matches = self.registry.match(event, self.graph)
            for b, rels in matches:
                if isinstance(b, RelationBehavior):
                    for r in rels:
                        if not self.budget.remaining():
                            break
                        self._invoke_relation(b, r, event)
                elif isinstance(b, LLMBehavior):
                    if not self.budget.remaining():
                        break
                    self._invoke_llm(b, event)
                else:
                    if not self.budget.remaining():
                        break
                    self._invoke(b, event)

    # ---------- invocation ----------

    def _invoke(self, b: Behavior, event: Event) -> None:
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

    def _invoke_llm(self, b: LLMBehavior, event: Event) -> None:
        """LLM behavior lifecycle. CONTRACT v0.6 #1, #2, #8, #9, #11.

        Order:
          behavior.started
            assemble prompt
            cache lookup
            if no hit AND max_cost_usd is set: count_tokens + pre-estimate
              → if would exceed: behavior.failed reason=budget.cost_exhausted
            emit llm.requested
            cache hit → use cached response (no API call)
            cache miss → provider.complete() → record to cache
            emit llm.responded
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

        # ---- 1. Assemble prompt ------------------------------------------
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

        prompt_hash = prompt.hash()

        # ---- 2. Cache lookup --------------------------------------------
        cached: Optional[Any] = None
        if self.replay_llm_cache and self._llm_cache is not None:
            cached = self._llm_cache.get(prompt_hash)

        # ---- 3. Pre-call cost gate (decision-4 adjustment) --------------
        pre_estimate_cost: Optional[Decimal] = None
        estimated_input_tokens: Optional[int] = None
        if cached is None and self.budget.has_cost_limit():
            try:
                estimated_input_tokens = self.llm_provider.count_tokens(
                    system=prompt.system,
                    messages=prompt.messages,
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
                # Conservative: assume the model uses the full output cap.
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

        # ---- 4. Emit llm.requested --------------------------------------
        requested_payload: dict[str, Any] = {
            "behavior": b.name,
            "model": prompt.model,
            "prompt_hash": prompt_hash,
            "prompt": prompt.to_hashable(),
            "deterministic": prompt.deterministic,
            "cache_hit": cached is not None,
        }
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
            caused_by=event.id,
        )

        # ---- 5. Cache-miss strict-replay check (decision-2 adjustment) --
        if self.replay_strict and self._strict_expected_hashes is not None:
            expected = self._strict_expected_hashes.pop(0) if self._strict_expected_hashes else None
            if expected is not None and expected != prompt_hash:
                raise ReplayDivergenceError(
                    event_id=requested_evt.id,
                    expected=f"prompt_hash={expected}",
                    actual=f"prompt_hash={prompt_hash}",
                )

        # ---- 6. Get the response (cache or provider) --------------------
        if cached is not None:
            response = cached
            # Cached parsed payloads are dicts (round-tripped through
            # JSON via the event log). Re-validate against the
            # behavior's schema so the handler always receives the
            # Pydantic instance it expects.
            if b.output_schema is not None and response.parsed is not None:
                if not isinstance(response.parsed, b.output_schema):
                    try:
                        response.parsed = b.output_schema.model_validate(
                            response.parsed
                        )
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
        else:
            try:
                response = self.llm_provider.complete(
                    system=prompt.system,
                    messages=prompt.messages,
                    model=prompt.model,
                    max_tokens=prompt.max_tokens,
                    temperature=prompt.temperature,
                    top_p=prompt.top_p,
                    output_schema=b.output_schema,
                    timeout_seconds=b.timeout_seconds,
                )
            except LLMBehaviorError as e:
                self._emit_behavior_failed(
                    b.name, event.id, e, reason=e.reason, extras=e.payload_extras
                )
                return
            except Exception as e:
                self._emit_behavior_failed(
                    b.name,
                    event.id,
                    e,
                    reason="llm.network_error",
                    extras={"model": prompt.model},
                )
                return
            if self._llm_cache is None:
                self._llm_cache = LLMCache()
            self._llm_cache.record(
                prompt_hash, response, requesting_event_id=requested_evt.id
            )
            # Real cost replaces the pre-call estimate (CONTRACT v0.6 #9).
            self.budget.add_cost(response.cost_usd)

        # ---- 7. Emit llm.responded --------------------------------------
        responded_payload = response.to_dict() | {
            "behavior": b.name,
            "prompt_hash": prompt_hash,
        }
        self._emit_llm_event(
            "llm.responded",
            responded_payload,
            actor=b.name,
            caused_by=requested_evt.id,
        )

        # ---- 8. Validate output (provider should have populated `parsed`)
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

        # ---- 9. Invoke developer handler with provenance stamping -------
        bgraph._llm_request_event_id = requested_evt.id  # noqa: SLF001
        try:
            b.handler(event, bgraph, ctx, response.parsed)
        except LLMBehaviorError as e:
            self._emit_behavior_failed(
                b.name, event.id, e, reason=e.reason, extras=e.payload_extras
            )
            return
        except Exception as e:
            self._emit_behavior_failed(b.name, event.id, e)
            return

        # ---- 10. behavior.completed -------------------------------------
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

    def _invoke_relation(self, b: RelationBehavior, relation, event: Event) -> None:
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

    def _emit_lifecycle(self, type_: str, payload: dict[str, Any]) -> None:
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
