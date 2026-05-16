# Active Graph v0 — Design Contract

These decisions are locked. Changing any of them is a breaking change to the
public API or to the trace format. Any change must update this file in the
same commit as the code change, with a one-line rationale appended to the
relevant section.

## 1. Identity and IDs

- Object IDs: `{type}#{n}` — e.g. `task#1`, `task#2`, `claim#3`. Single **global** monotonic counter prefixed by the object's type (so the third object created in a run gets `#3` regardless of type). This matches the README's expected quickstart trace.
- Event IDs: `evt_NNN` zero-padded to at least 3 digits, monotonic per graph, starting at `evt_001`.
- Relation IDs: `rel_NNN`.
- Patch IDs: `patch_NNN`.
- Frame IDs: `frame_NNN`.
- All IDs come from a single `IDGen` attached to the graph. Tests inject a deterministic generator. v0.5+ may swap to ULID behind the same factory; `id` stays `str`.

## 2. Event log is the source of truth (strict)

Every state change is an event first, projection second. The graph is
materialized from the log.

- `Graph.emit(event)` is the only mutation path.
- Convenience methods (`add_object`, `add_relation`, `patch_object`,
  `propose_patch`, `apply_patch`) build an event and call `emit`.
- The projector lives in `core/graph.py` and is the only code that touches
  `_objects` / `_relations`.
- No `_objects[id] = ...` outside the projector. Ever.

## 3. Event immutability

Events are append-only. Never edited, never deleted. Corrections happen by
emitting new events (e.g. `object.removed`).

## 4. Object versioning

- Field name: `version`. Integer, starts at 1.
- Increments by 1 on every successful `patch.applied`.
- Patches record `expected_version`. If the object's current version differs
  at apply time, the runtime emits `patch.rejected` with `current_version` in
  the payload and does not mutate.

## 5. Provenance

Every object, relation, and patch has a `provenance` dict written by the
runtime, never by the behavior:

```
{
  "created_by":      <behavior name | "user" | "system">,
  "caused_by_event": <event id | null>,
  "frame_id":        <frame id | null>,
  "timestamp":       <iso utc string>,
  "evidence":        [<event id>, ...]
}
```

Behaviors cannot set provenance. Any `provenance` key passed in `data` is
silently ignored.

## 6. Behavior signature

```python
def fn(event, graph, ctx) -> None
```

No `BehaviorResult` return type. The runtime observes mutations on the
constrained `graph` wrapper and synthesizes a result for tracing.

## 7. Constrained graph wrapper

Behaviors receive a `BehaviorGraph` instance, not the raw `Graph`. Allowed:

- `add_object(type, data) -> ObjectHandle`
- `add_relation(source, target, type, data=None) -> RelationHandle`
- `patch_object(id, updates) -> Patch`
- `propose_patch(target, op, value, evidence=None, rationale=None) -> Patch`
- `emit(event_type, payload) -> Event`

Disallowed: iterating over all objects, mutating provenance, modifying
events, accessing runtime internals. Reads go through `ctx.view`.

## 8. Determinism

Inside behaviors:

- No `random()` — use `ctx.random`.
- No `datetime.now()` — use `ctx.clock.now()`.
- No env reads, no file I/O, no network calls.

The runtime injects deterministic `clock` and `random` for replay.

## 9. Event namespace

`dot.lowercase`. Reserved namespaces:

- `runtime.*` — runtime lifecycle (`runtime.started`, `runtime.idle`, `runtime.budget_exhausted`).
- `behavior.*` — behavior lifecycle (`behavior.started`, `behavior.completed`, `behavior.failed`, `relation_behavior.started`, `relation_behavior.completed`, `relation_behavior.failed`).
- Standard graph events: `object.created`, `object.removed`, `relation.created`, `relation.removed`, `patch.proposed`, `patch.applied`, `patch.rejected`.
- `goal.created` is a convention emitted by `runtime.run_goal()`.
- Everything else is user-emitted.

## 10. Queue

Single in-process FIFO queue. Single-threaded loop. When multiple behaviors
match one event, they run in registration order. No async, no priority, no
parallelism in v0.

## 11. Views

Behaviors declare desired view via decorator metadata. The runtime constructs
the view before invocation. Behaviors do not build their own view from
`graph.query(...)`. Default view (if none declared) is full graph plus the
last 50 events.

v0 view spec keys: `around` (path expression), `depth` (BFS), `include_types`
(list[str]), `recent_events` (int). `token_budget` is parsed but ignored
until v0.6.

## 12. Patch atomicity

A patch targets exactly one object. Multi-object changes are multiple
patches. Apply is all-or-nothing for that one patch.

## 13. Failure mode

When a behavior raises an exception:

- Catch.
- Emit `behavior.failed` with payload:
  ```
  {
    "behavior":       <name>,
    "event_id":       <triggering event id>,
    "exception_type": <class name>,
    "message":        <str(exc)>,
    "traceback":      <full traceback string>
  }
  ```
- Continue the loop. Never re-raise into the runtime.

## 14. Project layout

```
activegraph/
  __init__.py          # public API surface only
  core/
    __init__.py
    ids.py
    clock.py
    event.py
    graph.py           # Object, Relation, Graph, projector
    patch.py
    view.py
  runtime/
    __init__.py
    runtime.py
    registry.py
    queue.py
    view_builder.py
    budget.py
    behavior_graph.py  # constrained wrapper
  behaviors/
    __init__.py
    decorators.py
    base.py
  policy.py
  frame.py
  trace/
    __init__.py
    printer.py
    causal.py
  store/
    __init__.py
    memory.py
tests/
examples/
```

Import direction: `core/` knows nothing about `runtime/` or `behaviors/`.
`behaviors/` imports `core/` only. `runtime/` imports `core/` and
`behaviors/`. Anything else is a layering violation.

## 15. Testing

- Every primitive: unit test.
- Every README example: integration test.
- Trace output: snapshot test. Requires deterministic `IDGen` and `clock`,
  injected via `Graph(ids=..., clock=...)`.

## 16. Out of scope for v0

- Persistence beyond in-memory (SQLite → v0.5).
- LLM behaviors (v0.6).
- Pattern subscriptions beyond `event_type + where` (Cypher → v0.7).
- Async / threading / distribution.
- Fork / diff (v0.5).
- Packs (v1.0).
- UI / server / HTTP.

If a v0 PR drifts toward any of these, reject.

## 17. API-first development

`examples/quickstart.py` is written before the runtime. The example defines
the public API surface; the runtime is built backward to make it run.

## 18. Trace format is contract

The trace output shown in the README is the contract. Snapshot-tested.
Format changes require updating the README and the snapshot in the same
commit.

### Formatter rules (v0)

Tag column is left-aligned, padded to 26 chars; if the tag itself is longer,
one space follows it.

| Event type                    | Rendering                                                          |
|-------------------------------|--------------------------------------------------------------------|
| `goal.created`                | `{actor}: "{payload.goal}"`                                        |
| `object.created`              | `{id} "{title or text}" ({status})` (parentheses omitted if no status) |
| `relation.created`            | `{source} --{type}--> {target}`                                    |
| `patch.applied`               | `{target} {field}: {old} -> {new}` (one line per changed field)    |
| `behavior.started`            | `{name}` (with `  (matched {event_type}: {object_id})` if applicable) |
| `behavior.completed`          | `{name} ({N} objects, {M} relations)`                              |
| `behavior.failed`             | `{name}: {exception_type}: {message}`                              |
| `relation_behavior.started`   | `{name}  (matched {event_type} on {relation_type} edge)`           |
| `relation_behavior.completed` | `{name}`                                                           |
| `runtime.idle`                | `queue empty, budget remaining`                                    |
| Other (user-emitted)          | rendered with tag `[event.emitted]` and content `{type} {k=v...}`  |

## Reconciliation notes

- README prose says `patch_object` emits `object.updated`; the README's
  expected trace shows `[patch.applied]`. Per #18 the trace wins.
  `patch_object` emits `patch.applied` events. `object.updated` is reserved
  but unused in v0.
