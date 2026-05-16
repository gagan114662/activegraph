"""Trace formatter. CONTRACT #18 — format is the public contract.

Layout: tag column is left-aligned, padded to 26 chars; if the tag itself is
longer, exactly one space follows it.

Standard event types get specific renderings (see CONTRACT for the table).
Anything else is rendered as `[event.emitted] {type} k=v...`.

CONTRACT v0.5 #22: replayed events are rendered with a `[replay.event]`
prefix. After the last replayed event, two synthetic lines appear so
operators can see the load boundary:
    [replay.complete] N events replayed, graph reconstructed
    [runtime.idle]    ready to resume
"""

from __future__ import annotations

from typing import Any

from activegraph.core.event import Event
from activegraph.core.graph import Graph


TAG_COL = 26


def _format_tag(tag_text: str) -> str:
    """Bracketed tag, left-padded to TAG_COL (or one trailing space if longer)."""
    bracketed = f"[{tag_text}]"
    if len(bracketed) >= TAG_COL:
        return bracketed + " "
    return bracketed.ljust(TAG_COL)


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'s' if n != 1 else ''}"


# ---------- per-event formatters ----------


def _fmt_goal_created(e: Event) -> str:
    actor = e.actor or "user"
    goal = e.payload.get("goal", "")
    return f'{_format_tag("goal.created")}{actor}: "{goal}"'


def _fmt_object_created(e: Event) -> str:
    o = e.payload.get("object", {})
    data = o.get("data", {})
    label = data.get("title") or data.get("text") or ""
    label_s = f' "{label}"' if label else ""
    status = data.get("status")
    status_s = f" ({status})" if status else ""
    return f'{_format_tag("object.created")}{o.get("id", "?")}{label_s}{status_s}'


def _fmt_object_removed(e: Event) -> str:
    return f'{_format_tag("object.removed")}{e.payload.get("id", "?")}'


def _fmt_relation_created(e: Event) -> str:
    r = e.payload.get("relation", {})
    return (
        f'{_format_tag("relation.created")}'
        f'{r.get("source", "?")} --{r.get("type", "?")}--> {r.get("target", "?")}'
    )


def _fmt_relation_removed(e: Event) -> str:
    return f'{_format_tag("relation.removed")}{e.payload.get("id", "?")}'


def _fmt_patch_applied(e: Event) -> str:
    target = e.payload.get("target", "?")
    diff = e.payload.get("diff", {})
    if not diff:
        return f'{_format_tag("patch.applied")}{target} (no change)'
    lines = []
    for field, change in diff.items():
        old = change.get("old")
        new = change.get("new")
        body = f"{target} {field}: {old} -> {new}"
        lines.append(f'{_format_tag("patch.applied")}{body}')
    return "\n".join(lines)


def _fmt_patch_proposed(e: Event) -> str:
    p = e.payload.get("patch", {})
    return (
        f'{_format_tag("patch.proposed")}'
        f'{p.get("target", "?")} {p.get("op", "?")} by {p.get("proposed_by", "?")}'
    )


def _fmt_patch_rejected(e: Event) -> str:
    return (
        f'{_format_tag("patch.rejected")}'
        f'{e.payload.get("patch_id", "?")}: {e.payload.get("reason", "?")}'
    )


def _fmt_behavior_started(e: Event) -> str:
    name = e.payload.get("behavior", "?")
    triggering_type = e.payload.get("triggering_event_type")
    triggering_id = e.payload.get("triggering_object_id")
    if triggering_type and triggering_id:
        return f'{_format_tag("behavior.started")}{name}  (matched {triggering_type}: {triggering_id})'
    return f'{_format_tag("behavior.started")}{name}'


def _fmt_relation_behavior_started(e: Event) -> str:
    name = e.payload.get("behavior", "?")
    triggering_type = e.payload.get("triggering_event_type", "?")
    relation_type = e.payload.get("relation_type", "?")
    return (
        f'{_format_tag("relation_behavior.started")}'
        f'{name}  (matched {triggering_type} on {relation_type} edge)'
    )


def _fmt_behavior_completed(e: Event) -> str:
    name = e.payload.get("behavior", "?")
    n_obj = int(e.payload.get("objects_created", 0))
    n_rel = int(e.payload.get("relations_created", 0))
    # Count summary only when behavior produced structure (>= 2 mutations
    # combined). Single-action behaviors render as just `name`. See CONTRACT.
    if n_obj + n_rel >= 2:
        return (
            f'{_format_tag("behavior.completed")}'
            f'{name} ({_plural(n_obj, "object")}, {_plural(n_rel, "relation")})'
        )
    return f'{_format_tag("behavior.completed")}{name}'


def _fmt_behavior_failed(e: Event) -> str:
    name = e.payload.get("behavior", "?")
    et = e.payload.get("exception_type", "?")
    msg = e.payload.get("message", "")
    return f'{_format_tag("behavior.failed")}{name}: {et}: {msg}'


def _fmt_runtime_idle(_: Event) -> str:
    return f'{_format_tag("runtime.idle")}queue empty, budget remaining'


def _fmt_runtime_budget_exhausted(e: Event) -> str:
    by = e.payload.get("exhausted_by", "?")
    return f'{_format_tag("runtime.budget_exhausted")}stopped: {by}'


def _fmt_event_emitted(e: Event) -> str:
    """Fallback for user-emitted (custom) events."""
    payload_kvs = []
    for k, v in (e.payload or {}).items():
        payload_kvs.append(f"{k}={_short(v)}")
    body = " ".join([e.type] + payload_kvs)
    return f'{_format_tag("event.emitted")}{body}'


def _short(v: Any) -> str:
    if isinstance(v, str):
        return v
    return repr(v)


_FORMATTERS = {
    "goal.created": _fmt_goal_created,
    "object.created": _fmt_object_created,
    "object.removed": _fmt_object_removed,
    "relation.created": _fmt_relation_created,
    "relation.removed": _fmt_relation_removed,
    "patch.applied": _fmt_patch_applied,
    "patch.proposed": _fmt_patch_proposed,
    "patch.rejected": _fmt_patch_rejected,
    "behavior.started": _fmt_behavior_started,
    "behavior.completed": _fmt_behavior_completed,
    "behavior.failed": _fmt_behavior_failed,
    "relation_behavior.started": _fmt_relation_behavior_started,
    "runtime.idle": _fmt_runtime_idle,
    "runtime.budget_exhausted": _fmt_runtime_budget_exhausted,
}


def format_event(event: Event) -> str:
    fn = _FORMATTERS.get(event.type, _fmt_event_emitted)
    return fn(event)


# ---------- replay rendering (CONTRACT v0.5 #22) ----------


def _fmt_replay(event: Event) -> str:
    """Render a replayed event with the `[replay.event]` prefix.

    Format: `[replay.event] <evt_id> <event.type> <one-line summary>`
    """
    t = event.type
    p = event.payload or {}
    if t == "object.created":
        o = p.get("object", {})
        oid = o.get("id", "?")
        label = (o.get("data") or {}).get("title") or (o.get("data") or {}).get("text") or ""
        label_s = f' "{label}"' if label else ""
        body = f"{event.id} {t} {oid}{label_s}"
    elif t == "relation.created":
        r = p.get("relation", {})
        body = f'{event.id} {t} {r.get("source")} --{r.get("type")}--> {r.get("target")}'
    elif t == "patch.applied":
        body = f'{event.id} {t} {p.get("target", "?")}'
    elif t == "goal.created":
        body = f'{event.id} {t} "{p.get("goal", "")}"'
    elif t in ("behavior.started", "behavior.completed", "behavior.failed", "relation_behavior.started"):
        body = f'{event.id} {t} {p.get("behavior", "?")}'
    else:
        body = f"{event.id} {t}"
    return f'{_format_tag("replay.event")}{body}'


def _fmt_replay_complete(n: int) -> str:
    return f'{_format_tag("replay.complete")}{n} events replayed, graph reconstructed'


def _fmt_replay_ready() -> str:
    return f'{_format_tag("runtime.idle")}ready to resume'


# ---------- Trace facade exposed via runtime.trace ----------


class Trace:
    def __init__(self, graph: Graph) -> None:
        self._graph = graph

    def lines(self) -> list[str]:
        replayed = self._graph.replayed_ids
        replayed_count = len(replayed)
        out: list[str] = []
        emitted_boundary = False
        seen_replayed = 0
        for e in self._graph.events:
            if e.id in replayed:
                out.append(_fmt_replay(e))
                seen_replayed += 1
                continue
            if replayed_count > 0 and not emitted_boundary:
                out.append(_fmt_replay_complete(replayed_count))
                out.append(_fmt_replay_ready())
                emitted_boundary = True
            line = format_event(e)
            out.append(line)
        if replayed_count > 0 and not emitted_boundary:
            out.append(_fmt_replay_complete(replayed_count))
            out.append(_fmt_replay_ready())
        return out

    def print(self) -> None:
        for line in self.lines():
            print(line)

    def export(self, path: str) -> None:
        with open(path, "w") as f:
            for line in self.lines():
                f.write(line + "\n")

    def causal_chain(self, object_id: str) -> str:
        from activegraph.trace.causal import causal_chain

        return causal_chain(self._graph, object_id)
