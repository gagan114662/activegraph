"""The runtime loop. Single-threaded FIFO. CONTRACT #10.

Responsibilities:
- Subscribe to graph events, enqueue them.
- Pop events, find matching behaviors, invoke each in registration order.
- Wrap behavior calls with behavior.started / behavior.completed
  (or relation_behavior.started / behavior.completed for relation behaviors).
- Catch any behavior exception, emit behavior.failed (CONTRACT #13).
- Stop on idle or budget exhaustion.
"""

from __future__ import annotations

import json
import random as _random
import traceback
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Optional, Union

from activegraph.behaviors.base import Behavior, RelationBehavior
from activegraph.behaviors.decorators import get_registry
from activegraph.core.event import Event
from activegraph.core.graph import Graph
from activegraph.core.view import View
from activegraph.frame import Frame
from activegraph.policy import Policy
from activegraph.runtime.behavior_graph import BehaviorGraph
from activegraph.runtime.budget import Budget
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


class Runtime:
    def __init__(
        self,
        graph: Graph,
        behaviors: Optional[Iterable[Union[Behavior, RelationBehavior]]] = None,
        frame: Optional[Frame] = None,
        policy: Optional[Policy] = None,
        budget: Optional[dict[str, Any]] = None,
        seed: int = 0,
    ) -> None:
        self.graph = graph
        self.frame = frame
        self.policy = policy
        self.budget = Budget(budget or {})
        self._random = _random.Random(seed)

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
        # Subscribe AFTER setting _inside_dispatch so listener works.
        graph.add_listener(self._on_event)

        self._idle_emitted = False

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
        self.registry = Registry(source)

    def run_goal(self, goal: str, *, actor: str = "user") -> None:
        self._ensure_registry()
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


def _maybe_object_id(event: Event) -> Optional[str]:
    obj = event.payload.get("object") if isinstance(event.payload, dict) else None
    if isinstance(obj, dict):
        return obj.get("id")
    return None
