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

---

# Active Graph v0.5 — Resumability addendum

v0.5 makes persistence physical. The event log moves from a Python list
into a SQLite file, with save / load / fork / diff on the runtime. v0
decisions all remain in force; the items below are additions and a
couple of small reconciliations.

## v0.5 #1. Event log is the canonical source of truth, persisted

Reaffirms v0 #2. v0.5 stores append events to durable storage as they
are emitted. The graph projection is rebuilt from the log on load. No
separate "graph snapshot" file. Snapshots are a v1+ optimization.

## v0.5 #2. EventStore interface

Abstract per-run interface in `store/base.py`:
```
append(event)
iter_events(after=None, until=None)
get_event(id)
count()
truncate_after(event_id)
close()
```
Two implementations ship: `InMemoryEventStore`, `SQLiteEventStore`. No
queries, no indexes beyond what the backend gives you. This is an event
log, not a database.

## v0.5 #3. SQLite schema (locked)

```
events(seq INTEGER PRIMARY KEY AUTOINCREMENT,
       id TEXT NOT NULL,
       type TEXT NOT NULL,
       actor TEXT,
       payload TEXT NOT NULL,
       frame_id TEXT,
       caused_by TEXT,
       timestamp TEXT NOT NULL,
       run_id TEXT NOT NULL,
       UNIQUE(id, run_id))

runs(run_id TEXT PRIMARY KEY,
     parent_run_id TEXT,
     forked_at_event_id TEXT,
     label TEXT,
     created_at TEXT NOT NULL,
     goal TEXT,
     frame_id TEXT)

meta(key TEXT PRIMARY KEY,
     value TEXT NOT NULL)        -- holds schema_version since day one.
```

`seq` is the projection ordering authority, not `timestamp`. WAL +
`synchronous=NORMAL` for write performance; safe across process crashes.

### DIFF: UNIQUE constraint scope

The locked draft said `id TEXT NOT NULL UNIQUE` (globally unique).
Decision #12 says logical ids are scoped to `run_id` — a fork preserves
the parent's `evt_017`. The constraint is therefore
`UNIQUE(id, run_id)`. Column shape unchanged.

## v0.5 #4. JSON serialization

Event payloads serialize as JSON. Not pickle, not msgpack. Decimals →
canonical strings; datetimes → ISO 8601; sets → sorted lists. Loading
does NOT reverse-coerce — payloads stay flat JSON primitives on the
read side. Non-serializable payloads raise
`NonSerializableEventError` at `Graph.emit` time, before any state
mutation.

## v0.5 #5. Save and load API

```
Runtime(graph, persist_to="run.db")   # attaches a SQLite store
Runtime(graph)                        # in-memory; late-bind via save_state
runtime.save_state()                  # flush (must have store attached)
runtime.save_state(path="run.db")     # late-bind; copies in-memory events
Runtime.load(path, run_id=None)       # rebuild + continue
```

Save with an attached store is a flush, not a snapshot. The store
already has every event because writes are continuous.

## v0.5 #6. Run identity

Every run has a `run_id` (ULID). One SQLite file holds many runs. Load
without `run_id` selects the most recently written-to run.

## v0.5 #7. Determinism becomes load-bearing

`replay_strict=True` on `Runtime.load` re-fires behaviors from the
recorded seed events (events with no `caused_by`) into a fresh Graph
and compares the new event stream to the recorded one. First mismatch
raises `ReplayDivergenceError(event_id, expected, actual)`. Debugging
mode, not always-on.

### Known limitation: payload drift

v0.5 compares the event-type stream (id, type). It catches categorical
non-determinism — different number of events, different types in
different positions — which is what actually breaks resume in v0.5.
Payload-only drift (same shape, different values, e.g. a random number
inside a payload) is NOT detected. This is deferred to v0.6, when LLM
behaviors land and payload non-determinism becomes the dominant failure
mode (temperature, sampling). The v0.6 tightening will compare full
event payloads with a configurable allow-list of fields that may drift
(e.g. timestamps).

## v0.5 #8. In-flight loss + unfired re-queue

In-flight behavior loss on crash is accepted: behaviors that started
but did not complete lose their post-crash work, unless they already
emitted events.

### DIFF: re-queue unfired events on load

The draft said "the queue starts empty on load". Taken literally, that
breaks the budget-exhaustion resume case — events sitting in the queue
when the runtime stopped never fire. v0.5 ships the spec's intent with
a useful default:

- On load, events with NO `behavior.started` referencing them are
  re-queued. They fire on the next `run_until_idle` / `run_goal`.
- Events that any behavior started on (even if it crashed mid-way)
  are NOT re-queued.

In-flight loss is preserved (the original tradeoff); resume after
budget exhaustion now works.

## v0.5 #9. Fork semantics

```
fork = runtime.fork(at_event="evt_073", label="alternative-thesis")
```

New `run_id`, copy of parent log up to and including `at_event`,
parent untouched, independent run, forks-of-forks supported.

## v0.5 #10. Diff semantics

```
diff = runtime.diff(other)
diff.shared_events / parent_only_events / fork_only_events
diff.divergent_objects / divergent_relations
```

Structural only — lifecycle events (`behavior.*`,
`relation_behavior.*`, `runtime.*`) are excluded from the event
partition. Semantic comparison is a behavior's job. Shared prefix
requires matching `(id, type, payload)` so colliding ids after the
fork point don't get flattened.

## v0.5 #11. Fork copies event rows

Copy rows under the new `run_id`. Storage doubles per fork. Acceptable
for v0.5. Copy-on-write row sharing is a v1+ optimization.

## v0.5 #12. IDs are scoped to run_id

Across a fork, object/event/relation counters are reseeded from the
forked log. Two forks from the same point can produce different
`task#5` objects with the same logical id — fine, they live in
different runs.

## v0.5 #13. Provenance carries run_id

Every object, relation, and patch records `provenance.run_id`.
Auto-stamped by the runtime, never by behaviors.

## v0.5 #14. Replay is not the same as run

Lock the boundary in code:
- `Graph.emit(event)` — live: append, project, persist (if store),
  notify listeners.
- `Graph._replay_event(event)` — replay: append, project, mark as
  replayed. No persist, no listeners. Used by `Runtime.load` and
  `Runtime.fork`.

Replayed event ids are tracked in `Graph._replayed_ids` so the trace
printer can render them distinctly.

## v0.5 #15. The projector is module-level

`apply_event(graph, event)` is the only function that mutates
`_objects` / `_relations` / `_patches`. Called by both live and replay
paths. Extracted from `Graph._project` in v0.5.

## v0.5 #16. Backward compatibility

A `Runtime(graph)` without `persist_to` behaves exactly as it did in
v0. All v0 tests pass unchanged. Persistence is strictly opt-in.

## v0.5 #17. Migrations

`meta.schema_version` exists from day one. Bumping it is the migration
hook.

## v0.5 #18. Test scope

- Round-trip, resume after budget, chaos (raise mid-behavior), fork,
  fork-of-fork, diff, replay-strict happy path, replay-strict
  divergence, JSON edge cases, 10k events under 2 seconds soft target.
- No LLM, pattern, pack, or concurrency tests.

## v0.5 #19. Out of scope

- LLM behaviors (v0.6)
- Cypher pattern subscriptions (v0.7)
- Packs (v1.0)
- Multi-process / distributed runtime
- Real-time graph subscriptions
- Remote storage backends (Postgres, FalkorDB, Neo4j)
- Any UI

## v0.5 #20. API-first

`examples/resume_and_fork.py` is written before the persistence layer;
the implementation is built backward to make it run. Same as v0 #17.

## v0.5 #21. README updates ship with the implementation

The `Replay and resume` section matches the implementation exactly.
v0 trace snapshot stays green. v0.5 adds `replay_trace.txt` as a
second snapshot.

## v0.5 #22. Trace format addition for replay

Replayed events render with `[replay.event]` and one-line summaries.
After the last replayed event:

```
[replay.complete]         N events replayed, graph reconstructed
[runtime.idle]            ready to resume
```

These trace lines are NOT events in the log — the synthetic boundary
lines are computed by the printer from `graph.replayed_ids`. Otherwise
saving + loading would recursively re-emit them.

Snapshot-tested in `tests/test_replay_trace_snapshot.py`.
