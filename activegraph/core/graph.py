"""Object, Relation, Graph + projector.

CONTRACT #2 (strict): Graph state is materialized from the event log.
`emit(event)` is the only mutator. Convenience methods (`add_object`,
`add_relation`, `patch_object`, `propose_patch`, `apply_patch`, etc.) all
build an Event and call emit.

CONTRACT v0.5 #15: the projector is `apply_event(graph, event)`, a
module-level function — the ONLY thing that mutates graph state. It is
called from two paths:
  - `Graph.emit` for live events (also persists + notifies listeners)
  - `Graph._replay_event` for replay (silent: no persist, no notify)
Two callers, one code path.

CONTRACT #5 (provenance): every object/relation/patch carries a provenance
dict written here, never by the behavior. Behaviors pass `data`; we strip
any `provenance` key they sneak in.

CONTRACT #4 (versioning): every object has a monotonic `version` int that
bumps on every patch.applied. Patches record `expected_version`.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Callable, Optional

from activegraph.core.clock import Clock
from activegraph.core.event import Event
from activegraph.core.ids import IDGen
from activegraph.core.patch import Patch


# ---------- handles ----------


@dataclass
class Object:
    id: str
    type: str
    data: dict[str, Any]
    version: int
    provenance: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "data": copy.deepcopy(self.data),
            "version": self.version,
            "provenance": copy.deepcopy(self.provenance),
        }


@dataclass
class Relation:
    id: str
    source: str
    target: str
    type: str
    data: dict[str, Any]
    provenance: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source": self.source,
            "target": self.target,
            "type": self.type,
            "data": copy.deepcopy(self.data),
            "provenance": copy.deepcopy(self.provenance),
        }


# ---------- graph ----------


def _strip_provenance(data: dict[str, Any]) -> dict[str, Any]:
    """Behaviors do not get to set provenance (CONTRACT #5)."""
    if not isinstance(data, dict):
        return data
    return {k: v for k, v in data.items() if k != "provenance"}


def _diff(old: dict[str, Any], updates: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return per-field {old, new} for fields that actually change."""
    out: dict[str, dict[str, Any]] = {}
    for k, new_v in updates.items():
        old_v = old.get(k, _MISSING)
        if old_v != new_v:
            out[k] = {"old": None if old_v is _MISSING else old_v, "new": new_v}
    return out


_MISSING = object()


class Graph:
    """Event-sourced graph. The log is truth; objects/relations are projection."""

    def __init__(
        self,
        ids: Optional[IDGen] = None,
        clock: Optional[Clock] = None,
        run_id: Optional[str] = None,
    ) -> None:
        self.ids = ids or IDGen()
        self.clock = clock or Clock()
        # CONTRACT v0.5 #6: every graph has a run_id.
        self.run_id: str = run_id or self.ids.run()

        # projected state — touched ONLY by apply_event (CONTRACT v0.5 #15)
        self._objects: dict[str, Object] = {}
        self._relations: dict[str, Relation] = {}
        self._patches: dict[str, Patch] = {}

        # the log
        self._events: list[Event] = []

        # listeners (the runtime queue subscribes here)
        self._listeners: list[Callable[[Event], None]] = []

        # CONTRACT v0.5 #14: track which events were replayed (not live).
        # The trace printer renders them with a [replay.event] prefix.
        self._replayed_ids: set[str] = set()

        # Optional persistence sink (attached by Runtime when persist_to=...).
        self._store = None  # type: ignore[assignment]

    # ---------- read API ----------

    @property
    def events(self) -> list[Event]:
        return list(self._events)

    @property
    def replayed_ids(self) -> frozenset[str]:
        return frozenset(self._replayed_ids)

    def get_object(self, id_: str) -> Optional[Object]:
        return self._objects.get(id_)

    def get_relation(self, id_: str) -> Optional[Relation]:
        return self._relations.get(id_)

    def get_patch(self, id_: str) -> Optional[Patch]:
        return self._patches.get(id_)

    def all_objects(self) -> list[Object]:
        return list(self._objects.values())

    def all_relations(self) -> list[Relation]:
        return list(self._relations.values())

    def get_relations(
        self,
        object_id: Optional[str] = None,
        type: Optional[str] = None,
        direction: str = "both",
    ) -> list[Relation]:
        out: list[Relation] = []
        for r in self._relations.values():
            if type is not None and r.type != type:
                continue
            if object_id is not None:
                if direction == "outgoing" and r.source != object_id:
                    continue
                if direction == "incoming" and r.target != object_id:
                    continue
                if direction == "both" and object_id not in (r.source, r.target):
                    continue
            out.append(r)
        return out

    def neighborhood(self, object_id: str, depth: int = 1) -> tuple[list[Object], list[Relation]]:
        if object_id not in self._objects:
            return ([], [])
        seen_objs = {object_id}
        frontier = {object_id}
        seen_rels: set[str] = set()
        for _ in range(depth):
            next_frontier: set[str] = set()
            for r in self._relations.values():
                if r.source in frontier or r.target in frontier:
                    seen_rels.add(r.id)
                    if r.source not in seen_objs:
                        next_frontier.add(r.source)
                    if r.target not in seen_objs:
                        next_frontier.add(r.target)
            seen_objs |= next_frontier
            frontier = next_frontier
            if not frontier:
                break
        return (
            [self._objects[i] for i in seen_objs if i in self._objects],
            [self._relations[i] for i in seen_rels if i in self._relations],
        )

    def query(
        self,
        object_type: Optional[str] = None,
        where: Optional[dict[str, Any]] = None,
    ) -> list[Object]:
        out: list[Object] = []
        for o in self._objects.values():
            if object_type is not None and o.type != object_type:
                continue
            if where and not _eval_where_on_object(where, o):
                continue
            out.append(o)
        return out

    def has_object_of_type(self, type_: str) -> bool:
        return any(o.type == type_ for o in self._objects.values())

    # ---------- listener API (runtime hooks here) ----------

    def add_listener(self, fn: Callable[[Event], None]) -> None:
        self._listeners.append(fn)

    # ---------- store attachment (Runtime sets this) ----------

    def attach_store(self, store) -> None:
        """Wire an EventStore as the durability sink. Idempotent on the same
        store. Calling with a *different* store after events exist is an error
        — events would be persisted in two places and you'd lose history.
        """
        if self._store is store:
            return
        if self._store is not None:
            raise RuntimeError("graph already has a store attached")
        self._store = store

    @property
    def store(self):
        return self._store

    # ---------- the only mutator (live path) ----------

    def emit(self, event: Event) -> Event:
        """Append to log, project, persist (if attached), notify. CONTRACT #2."""
        # Fail-fast serialization check at emit time so bad payloads never
        # land in the in-memory log either (CONTRACT v0.5 #4).
        if self._store is not None:
            from activegraph.store.serde import validate_event

            validate_event(event)
        self._events.append(event)
        apply_event(self, event)
        if self._store is not None:
            self._store.append(event)
        for listener in self._listeners:
            listener(event)
        return event

    # ---------- the only mutator (replay path) ----------

    def _replay_event(self, event: Event) -> None:
        """Apply a recorded event WITHOUT persisting or firing listeners.

        Used only by `Runtime.load` and `Runtime.fork`. CONTRACT v0.5 #14:
        replay rebuilds graph state; it does NOT fire behaviors.
        """
        self._events.append(event)
        apply_event(self, event)
        self._replayed_ids.add(event.id)

    # ---------- convenience builders (each builds an Event and emits) ----------

    def add_object(
        self,
        type: str,
        data: dict[str, Any],
        *,
        actor: str = "system",
        caused_by: Optional[str] = None,
        frame_id: Optional[str] = None,
        evidence: Optional[list[str]] = None,
        llm_request_event_id: Optional[str] = None,
        tool_request_event_ids: Optional[list[str]] = None,
    ) -> Object:
        obj_id = self.ids.object(type)
        clean = _strip_provenance(copy.deepcopy(data))
        provenance = self._provenance(
            actor,
            caused_by,
            frame_id,
            evidence,
            llm_request_event_id,
            tool_request_event_ids,
        )
        payload = {
            "object": {
                "id": obj_id,
                "type": type,
                "data": clean,
                "version": 1,
                "provenance": provenance,
            },
            "id": obj_id,
        }
        event = Event(
            id=self.ids.event(),
            type="object.created",
            payload=payload,
            actor=actor,
            frame_id=frame_id,
            caused_by=caused_by,
            timestamp=self.clock.now(),
        )
        self.emit(event)
        return self._objects[obj_id]

    def add_relation(
        self,
        source: str,
        target: str,
        type: str,
        data: Optional[dict[str, Any]] = None,
        *,
        actor: str = "system",
        caused_by: Optional[str] = None,
        frame_id: Optional[str] = None,
        llm_request_event_id: Optional[str] = None,
        tool_request_event_ids: Optional[list[str]] = None,
    ) -> Relation:
        rel_id = self.ids.relation()
        clean = _strip_provenance(copy.deepcopy(data or {}))
        provenance = self._provenance(
            actor,
            caused_by,
            frame_id,
            [],
            llm_request_event_id,
            tool_request_event_ids,
        )
        payload = {
            "relation": {
                "id": rel_id,
                "source": source,
                "target": target,
                "type": type,
                "data": clean,
                "provenance": provenance,
            },
            "id": rel_id,
            "source": source,
            "target": target,
        }
        event = Event(
            id=self.ids.event(),
            type="relation.created",
            payload=payload,
            actor=actor,
            frame_id=frame_id,
            caused_by=caused_by,
            timestamp=self.clock.now(),
        )
        self.emit(event)
        return self._relations[rel_id]

    def remove_relation(
        self,
        relation_id: str,
        *,
        actor: str = "system",
        caused_by: Optional[str] = None,
        frame_id: Optional[str] = None,
    ) -> None:
        if relation_id not in self._relations:
            return
        event = Event(
            id=self.ids.event(),
            type="relation.removed",
            payload={"id": relation_id},
            actor=actor,
            frame_id=frame_id,
            caused_by=caused_by,
            timestamp=self.clock.now(),
        )
        self.emit(event)

    def remove_object(
        self,
        object_id: str,
        *,
        actor: str = "system",
        caused_by: Optional[str] = None,
        frame_id: Optional[str] = None,
    ) -> None:
        if object_id not in self._objects:
            return
        event = Event(
            id=self.ids.event(),
            type="object.removed",
            payload={"id": object_id},
            actor=actor,
            frame_id=frame_id,
            caused_by=caused_by,
            timestamp=self.clock.now(),
        )
        self.emit(event)

    def patch_object(
        self,
        target: str,
        updates: dict[str, Any],
        *,
        actor: str = "system",
        caused_by: Optional[str] = None,
        frame_id: Optional[str] = None,
        rationale: Optional[str] = None,
        evidence: Optional[list[str]] = None,
        llm_request_event_id: Optional[str] = None,
        tool_request_event_ids: Optional[list[str]] = None,
    ) -> Patch:
        """Auto-apply shortcut: build patch, version-check, emit applied/rejected."""
        obj = self._objects.get(target)
        if obj is None:
            raise KeyError(f"unknown object: {target}")
        clean = _strip_provenance(copy.deepcopy(updates))
        patch = Patch(
            id=self.ids.patch(),
            target=target,
            op="update",
            value=clean,
            expected_version=obj.version,
            proposed_by=actor,
            rationale=rationale,
            evidence=list(evidence or []),
            status="applied",
            provenance=self._provenance(
                actor,
                caused_by,
                frame_id,
                evidence,
                llm_request_event_id,
                tool_request_event_ids,
            ),
        )
        diff = _diff(obj.data, clean)
        event = Event(
            id=self.ids.event(),
            type="patch.applied",
            payload={
                "patch": patch.to_dict(),
                "target": target,
                "diff": diff,
            },
            actor=actor,
            frame_id=frame_id,
            caused_by=caused_by,
            timestamp=self.clock.now(),
        )
        self.emit(event)
        return self._patches[patch.id]

    def propose_patch(
        self,
        target: str,
        op: str,
        value: dict[str, Any],
        *,
        proposed_by: str,
        rationale: Optional[str] = None,
        evidence: Optional[list[str]] = None,
        caused_by: Optional[str] = None,
        frame_id: Optional[str] = None,
        llm_request_event_id: Optional[str] = None,
        tool_request_event_ids: Optional[list[str]] = None,
    ) -> Patch:
        # Strip "object:" / "relation:" prefix if present (README sugar).
        normalized = target.split(":", 1)[1] if ":" in target else target
        obj = self._objects.get(normalized)
        expected_version = obj.version if obj else 0
        clean = _strip_provenance(copy.deepcopy(value))
        patch = Patch(
            id=self.ids.patch(),
            target=normalized,
            op=op,
            value=clean,
            expected_version=expected_version,
            proposed_by=proposed_by,
            rationale=rationale,
            evidence=list(evidence or []),
            status="proposed",
            provenance=self._provenance(
                proposed_by,
                caused_by,
                frame_id,
                evidence,
                llm_request_event_id,
                tool_request_event_ids,
            ),
        )
        event = Event(
            id=self.ids.event(),
            type="patch.proposed",
            payload={"patch": patch.to_dict()},
            actor=proposed_by,
            frame_id=frame_id,
            caused_by=caused_by,
            timestamp=self.clock.now(),
        )
        self.emit(event)
        return self._patches[patch.id]

    def apply_patch(
        self,
        patch_id: str,
        *,
        approved_by: str = "system",
        caused_by: Optional[str] = None,
        frame_id: Optional[str] = None,
    ) -> Event:
        patch = self._patches.get(patch_id)
        if patch is None:
            raise KeyError(f"unknown patch: {patch_id}")
        if patch.status != "proposed":
            raise ValueError(f"patch {patch_id} is {patch.status}, not proposed")
        target_obj = self._objects.get(patch.target)
        current_version = target_obj.version if target_obj else 0
        if current_version != patch.expected_version:
            return self._reject(
                patch_id,
                reason=f"version mismatch: expected {patch.expected_version}, got {current_version}",
                actor=approved_by,
                caused_by=caused_by,
                frame_id=frame_id,
            )
        diff = _diff(target_obj.data if target_obj else {}, patch.value)
        event = Event(
            id=self.ids.event(),
            type="patch.applied",
            payload={
                "patch": {**patch.to_dict(), "status": "applied"},
                "target": patch.target,
                "diff": diff,
                "approved_by": approved_by,
            },
            actor=approved_by,
            frame_id=frame_id,
            caused_by=caused_by,
            timestamp=self.clock.now(),
        )
        return self.emit(event)

    def reject_patch(
        self,
        patch_id: str,
        reason: str,
        *,
        actor: str = "system",
        caused_by: Optional[str] = None,
        frame_id: Optional[str] = None,
    ) -> Event:
        return self._reject(patch_id, reason, actor=actor, caused_by=caused_by, frame_id=frame_id)

    def _reject(
        self,
        patch_id: str,
        reason: str,
        *,
        actor: str,
        caused_by: Optional[str],
        frame_id: Optional[str],
    ) -> Event:
        patch = self._patches[patch_id]
        current = self._objects.get(patch.target)
        event = Event(
            id=self.ids.event(),
            type="patch.rejected",
            payload={
                "patch_id": patch_id,
                "target": patch.target,
                "reason": reason,
                "current_version": current.version if current else 0,
            },
            actor=actor,
            frame_id=frame_id,
            caused_by=caused_by,
            timestamp=self.clock.now(),
        )
        return self.emit(event)

    # ---------- provenance helper (CONTRACT v0.5 #13: includes run_id) ----------

    def _provenance(
        self,
        actor: str,
        caused_by: Optional[str],
        frame_id: Optional[str],
        evidence: Optional[list[str]],
        llm_request_event_id: Optional[str] = None,
        tool_request_event_ids: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        p: dict[str, Any] = {
            "created_by": actor,
            "caused_by_event": caused_by,
            "frame_id": frame_id,
            "timestamp": self.clock.now(),
            "evidence": list(evidence or []),
            "run_id": self.run_id,
        }
        # CONTRACT v0.6 #15: objects/relations/patches created inside an
        # @llm_behavior handler carry the llm.requested event id so causal
        # chain walks can cross the LLM boundary.
        if llm_request_event_id is not None:
            p["llm_request_event_id"] = llm_request_event_id
        # CONTRACT v0.7 #19: when the LLM behavior's turn loop invoked
        # tools, all contributing tool.requested event ids are stamped
        # here so causal-chain walks can enumerate every tool call.
        if tool_request_event_ids:
            p["tool_request_event_ids"] = list(tool_request_event_ids)
        return p


# ---------- the projector — module-level, single mutation code path ----------


def apply_event(graph: Graph, event: Event) -> None:
    """Project an event onto the graph's in-memory state.

    The ONLY function that mutates `_objects` / `_relations` / `_patches`.
    Called from `Graph.emit` (live) and `Graph._replay_event` (replay).
    Pure projection — no I/O, no listener calls, no event log mutation.
    """
    t = event.type
    p = event.payload

    if t == "object.created":
        o = p["object"]
        graph._objects[o["id"]] = Object(
            id=o["id"],
            type=o["type"],
            data=copy.deepcopy(o["data"]),
            version=o["version"],
            provenance=copy.deepcopy(o["provenance"]),
        )

    elif t == "object.removed":
        graph._objects.pop(p["id"], None)
        # cascade: drop relations touching it
        for rid in [
            r.id for r in graph._relations.values() if p["id"] in (r.source, r.target)
        ]:
            graph._relations.pop(rid, None)

    elif t == "relation.created":
        r = p["relation"]
        graph._relations[r["id"]] = Relation(
            id=r["id"],
            source=r["source"],
            target=r["target"],
            type=r["type"],
            data=copy.deepcopy(r["data"]),
            provenance=copy.deepcopy(r["provenance"]),
        )

    elif t == "relation.removed":
        graph._relations.pop(p["id"], None)

    elif t == "patch.proposed":
        patch_dict = p["patch"]
        graph._patches[patch_dict["id"]] = _patch_from_dict(patch_dict)

    elif t == "patch.applied":
        patch_dict = p["patch"]
        patch = _patch_from_dict({**patch_dict, "status": "applied"})
        graph._patches[patch.id] = patch
        obj = graph._objects.get(patch.target)
        if obj is not None:
            if patch.op == "update":
                obj.data.update(patch.value)
            elif patch.op == "replace":
                obj.data = copy.deepcopy(patch.value)
            obj.version += 1

    elif t == "patch.rejected":
        existing = graph._patches.get(p["patch_id"])
        if existing is not None:
            existing.status = "rejected"
            existing.rejection_reason = p["reason"]


def _patch_from_dict(d: dict[str, Any]) -> Patch:
    return Patch(
        id=d["id"],
        target=d["target"],
        op=d["op"],
        value=copy.deepcopy(d["value"]),
        expected_version=d["expected_version"],
        proposed_by=d["proposed_by"],
        rationale=d.get("rationale"),
        evidence=list(d.get("evidence", [])),
        status=d.get("status", "proposed"),
        rejection_reason=d.get("rejection_reason"),
        provenance=copy.deepcopy(d.get("provenance", {})),
    )


# ---------- where evaluator (used by query and matchers) ----------

_OPS = {
    ">": lambda a, b: a is not None and a > b,
    "<": lambda a, b: a is not None and a < b,
    ">=": lambda a, b: a is not None and a >= b,
    "<=": lambda a, b: a is not None and a <= b,
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
    "in": lambda a, b: a in b,
    "not in": lambda a, b: a not in b,
}


def _resolve_path(root: Any, path: list[str]) -> Any:
    cur = root
    for p in path:
        if isinstance(cur, dict):
            cur = cur.get(p)
        elif hasattr(cur, p):
            cur = getattr(cur, p)
        else:
            return None
        if cur is None:
            return None
    return cur


def evaluate_where(where: dict[str, Any], root: Any) -> bool:
    """Evaluate a where dict against a root (event payload, object, etc.).

    Keys are dotted paths. Values are either literals (equality) or
    `{"op": value}` dicts for comparisons.
    """
    for key, expected in where.items():
        actual = _resolve_path(root, key.split("."))
        if isinstance(expected, dict):
            for op, value in expected.items():
                fn = _OPS.get(op)
                if fn is None:
                    raise ValueError(f"unknown where operator: {op}")
                if not fn(actual, value):
                    return False
        else:
            if actual != expected:
                return False
    return True


def _eval_where_on_object(where: dict[str, Any], obj: Object) -> bool:
    """Where on a bare Object — keys are paths under data unless they start with one of the object fields."""
    root = {
        "id": obj.id,
        "type": obj.type,
        "data": obj.data,
        "version": obj.version,
        "provenance": obj.provenance,
        # also expose data fields at top level for convenience
        **obj.data,
    }
    return evaluate_where(where, root)
