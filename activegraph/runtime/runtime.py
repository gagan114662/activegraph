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
"""

from __future__ import annotations

import json
import random as _random
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Optional, Union

from activegraph.behaviors.base import Behavior, RelationBehavior
from activegraph.behaviors.decorators import get_registry
from activegraph.core.event import Event
from activegraph.core.graph import Graph
from activegraph.core.ids import IDGen
from activegraph.core.view import View
from activegraph.frame import Frame
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
    ) -> None:
        self.graph = graph
        self.frame = frame
        self.policy = policy
        self.budget = Budget(budget or {})
        self._random = _random.Random(seed)
        self.replay_strict = replay_strict

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
    ) -> "Runtime":
        """Open `path`, choose a run, replay its events, return a Runtime
        wired to continue from where the log left off.

        If `run_id` is None, loads the most recently appended-to run
        (CONTRACT v0.5 #6).
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

        rt = cls(
            graph,
            behaviors=behaviors,
            frame=frame,
            policy=policy,
            budget=budget,
            seed=seed,
            replay_strict=replay_strict,
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
            _verify_replay(graph, events, behaviors, frame, policy, budget, seed)

        return rt

    def fork(
        self,
        at_event: str,
        label: Optional[str] = None,
        *,
        behaviors: Optional[Iterable[Union[Behavior, RelationBehavior]]] = None,
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

        return Runtime(
            fork_graph,
            behaviors=fork_behaviors,
            frame=self.frame,
            policy=self.policy,
            budget=None,  # fresh budget for the fork
            seed=0,
        )

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
) -> None:
    """Replay the run from scratch — fresh Graph, behaviors fire — and
    compare the resulting event stream to the recorded log.

    On the first mismatch (id or type), raise ReplayDivergenceError.
    """
    # Seed events: everything with no caused_by (goal.created, user-emitted
    # bootstrap events). Behaviors re-derive everything else.
    seed_events = [e for e in recorded_events if e.caused_by is None and not _is_lifecycle(e)]
    if not seed_events:
        return  # nothing to verify

    fresh = Graph(ids=IDGen(), run_id="verify_" + loaded_graph.run_id)
    fresh_rt = Runtime(
        fresh,
        behaviors=behaviors,
        frame=frame,
        policy=policy,
        budget=budget,
        seed=seed,
    )
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
