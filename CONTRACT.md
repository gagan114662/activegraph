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

---

# Active Graph v0.6 — LLM behaviors addendum

v0.6 puts LLMs onto the substrate without breaking what made the
substrate trustworthy. Every LLM call is two events in the log; the
parsed structured output is the only thing the developer touches; the
trace, provenance, budgets, and replay machinery all keep meaning.
v0/v0.5 decisions remain in force; the items below are additions and
a handful of explicit narrowings.

## v0.6 #1. An LLM call is an event (two events, actually)

Every LLM invocation emits a `llm.requested` (before the call —
payload includes full prompt, model, params, prompt hash) and a
`llm.responded` (after — payload includes raw text, parsed output
[JSON-dumped], tokens, cost, latency, finish reason, cache_hit flag).
These persist like any other event. Replay reads them back instead of
re-calling. This single decision is what keeps the rest of the system
working under LLMs.

`llm.requested.caused_by` = triggering event id.
`llm.responded.caused_by` = `llm.requested.id`.

`llm.*` are reserved namespaces. They flow through the queue normally
— user behaviors **can** subscribe to them (an audit-trail behavior
is a legitimate use case). The wrapper does not.

## v0.6 #2. `@llm_behavior` is sugar over `@behavior`

The decorator returns an `LLMBehavior` (subclass of `Behavior`). The
runtime owns the invocation lifecycle via `_invoke_llm`:

```
behavior.started
  build_prompt(event, graph)              # pure, no I/O
  cache lookup by prompt_hash             # if replay_llm_cache=True
  pre-call cost gate                      # if max_cost_usd and no cache hit
  emit llm.requested
  provider.complete()   |   cached response
  emit llm.responded
  handler(event, graph, ctx, parsed_output)
behavior.completed
```

The handler signature is `(event, graph, ctx, llm_output) -> None` —
the 4th arg is a Pydantic instance (or whatever `output_schema=` was).
The 3-arg `fn` field on `LLMBehavior` is unused; calling
`LLMBehavior.run()` directly raises. Per CONTRACT v0.6 invariant: the
runtime is the only thing that invokes LLM behaviors.

### DIFF: CONTRACT #6 (behavior signature)

CONTRACT #6 documents the 3-arg signature for `@behavior` /
`@relation_behavior`. `@llm_behavior` is an explicit exception: the
user-supplied function is a 4-arg handler that the decorator binds
via the runtime's `_invoke_llm` path. Regular `@behavior` and
`@relation_behavior` signatures are unchanged.

## v0.6 #3. `LLMProvider` protocol

```python
class LLMProvider(Protocol):
    def complete(self, *, system, messages, model, max_tokens,
                 temperature, top_p, output_schema, timeout_seconds) -> LLMResponse: ...
    def estimate_cost(self, *, input_tokens, output_tokens, model) -> Decimal: ...
    def count_tokens(self, *, system, messages, model) -> int: ...
```

All keyword-only. `LLMResponse` carries raw text, parsed structured
output (Pydantic instance when `output_schema` was passed and parsing
succeeded), input/output tokens, Decimal cost, latency, model id,
finish reason, optional seed (always `None` for Anthropic), cache_hit
flag, and `provider_meta`. `count_tokens` is on the protocol because
the budget gate needs official token counts (CONTRACT #10 carryover).

No streaming, no tool use, no multi-call orchestration. Deferred to
v0.7.

## v0.6 #4. Anthropic is the reference implementation

`AnthropicProvider` reads `ANTHROPIC_API_KEY`. The `anthropic` SDK is
optional (`pip install activegraph[llm]`). Pricing table is
class-level, overridable via `pricing=` kwarg; ships with current
Claude 4.x family rates (May 2026). Family-prefix lookup
(`claude-sonnet-4-6` resolves to the `claude-sonnet-4` row). Unknown
models fall back to sonnet-4 pricing.

`top_p < 1.0` is only forwarded when narrowing (the SDK default is
1.0; forwarding it forces a behavior change). `seed=` is never
forwarded — Anthropic's messages API does not accept one.

## v0.6 #5. Pydantic v2 as the schema language

Developers define output shapes as Pydantic models. The decorator
takes `output_schema=ClaimList`. The runtime serializes the schema
into the system prompt as JSON-schema, and (after the call) validates
the model response against the same class. Two distinct failure
modes:

- `llm.parse_error` — no JSON found in the response
- `llm.schema_violation` — JSON found but Pydantic rejected it

No silent retries. If the developer wants a retry, they write a
behavior that subscribes to `behavior.failed`.

## v0.6 #6. Prompt assembly is the runtime's job

The four sources, in this order, are always assembled by the runtime:

1. **system** — frame goal, frame constraints, behavior `description=`,
   output-schema reminder (in that order; absent sections are omitted)
2. **view** — serialized scoped graph view (see v0.6 #13)
3. **event** — triggering event, JSON-serialized, with volatile fields
   stripped (provenance, timestamps, run_id) so the prompt is
   content-stable across runs/forks
4. **instruction** — auto-derived from `creates=` and `output_schema=`

`prompt_template=` is the only escape hatch — a Python `str.format`
template that receives `{system}`, `{view}`, `{event}`,
`{instruction}`. There is no raw string-concat path.

`LLMBehavior.build_prompt(event, graph)` returns an `AssembledPrompt`
without making an API call. Public for debugging.

## v0.6 #7. Determinism mode is best-effort

`deterministic=True` forces `temperature=0` and `top_p=1`. The
`AssembledPrompt.deterministic` field is included in the hash so a
deterministic and a stochastic prompt with otherwise-identical
content hash differently. Anthropic's messages API has no `seed`
parameter; provider-side response drift remains best-effort.

This narrows but does not close the payload-drift limitation deferred
from v0.5 #7 — see v0.6 #22.

## v0.6 #8. Replay LLM cache

Content-keyed (`sha256(canonical_json({model, system, messages,
output_schema_name, output_schema_json, max_tokens, temperature,
top_p, deterministic}))`). The originating `llm.requested` event id
is stored alongside cached entries for trace lineage, but is NOT the
lookup key — cross-fork prompt-match requires content equality.

Population paths:
- `Runtime.load(..., replay_llm_cache=True)` — pre-populates from
  the loaded log's `llm.responded` events.
- `runtime.fork(at_event, ..., replay_llm_cache=True)` — pre-populates
  from the **parent's** full event log (not the fork's, which only
  has events up to and including `at_event`).
- `_verify_replay` — always populates the cache implicitly when
  `replay_strict=True`, regardless of the user-facing flag.
  Verification must not hit the live API.

Cached responses re-validate against the behavior's `output_schema`
before being handed to the handler (the round-trip through JSON
turns Pydantic instances into dicts).

### DIFF: prompt-hash mismatch under replay_strict

If a recorded `llm.requested` carries a `prompt_hash` that the
re-assembled prompt does NOT produce, the runtime raises
`ReplayDivergenceError(event_id=<new llm.requested id>,
expected="prompt_hash=<recorded>", actual="prompt_hash=<rebuilt>")`.
Same divergence-pinning pattern as v0.5 #7's event-stream comparison.
The cache cannot silently paper over genuine non-determinism in
prompt construction.

## v0.6 #9. Cost accounting in `Decimal`

`max_cost_usd` is tracked in `Decimal`; other budget dimensions stay
as floats. Pre-call estimate is conservative: input tokens (from
`provider.count_tokens(...)`) + `max_tokens` reservation as the
output estimate. If it would exceed the cap, the call is not made
and `behavior.failed reason="budget.cost_exhausted"` fires. After
the call, the actual usage cost (from `response.cost_usd`) is added
to `budget.cost_used`, replacing the conservative estimate.

`budget.snapshot()` exposes `cost_used_usd` and `cost_limit_usd` as
Decimal strings so consumers can choose precision.

## v0.6 #10. Token counting uses the provider's tokenizer

Anthropic's `count_tokens` is a network roundtrip. We only pay for it
when:
  (a) `budget.max_cost_usd` is set, AND
  (b) no cached response was found for this prompt hash.

Cache-hit paths skip token counting (decision-4 adjustment).
Budget-less runs skip it (no ceiling to enforce). Approximate
character-count estimation is forbidden for billing decisions.

## v0.6 #11. Failure modes are explicit `behavior.failed` events

No silent retries. No hidden backoff inside the provider. The
`behavior.failed` payload gains an optional `reason` field; absent
for v0/v0.5-shaped failures, set for LLM failures:

| `reason`                    | Source                                                 |
|-----------------------------|--------------------------------------------------------|
| `llm.network_error`         | Connection error / timeout                             |
| `llm.rate_limited`          | 429-shaped error; `retry_after_seconds` if available   |
| `llm.parse_error`           | Provider returned text with no parseable JSON          |
| `llm.schema_violation`      | Pydantic rejected the JSON                             |
| `llm.fixture_missing`       | `RecordedLLMProvider` had no fixture for the prompt    |
| `llm.prompt_assembly_error` | Prompt construction itself raised (rare)               |
| `budget.cost_exhausted`     | Pre-call estimate would exceed `max_cost_usd`          |

Wrappers signal these via `LLMBehaviorError(reason, message,
payload_extras=...)` which the runtime catches and merges into the
`behavior.failed` payload. Other exception types fall through to
CONTRACT #13 unchanged (no `reason`).

### DIFF: CONTRACT #13

CONTRACT #13's payload becomes a superset: original keys plus
optional `reason` plus optional `payload_extras` keys (free-form,
LLM-specific). No v0/v0.5 emissions change shape.

## v0.6 #12. Recorded-LLM test mode

`RecordedLLMProvider(fixtures_dir)` reads `{prompt_hash}.json`
fixtures and serves them on prompt-hash hits; misses raise
`LLMBehaviorError(reason="llm.fixture_missing")`. No silent
fallthrough to a real call.

`RecordingLLMProvider(inner, fixtures_dir)` wraps another provider
and writes each response to disk. Use once with a real provider
(under `pytest.mark.records_llm` opt-in) to seed fixtures; commit
the resulting files; run thereafter against `RecordedLLMProvider`.

### Fixture file format

```json
{
  "prompt_hash": "<sha256_hex>",
  "recorded_at": "2026-05-15T10:32:01Z",
  "model": "claude-sonnet-4-5",
  "prompt":   { ... only this hashes ... },
  "response": { ... what the provider returned ... }
}
```

`recorded_at` is intentionally OUTSIDE the hashed `prompt` payload so
it doesn't perturb lookups but stays available when fixtures drift
(decision-3 adjustment).

## v0.6 #13. View serialization format is part of the contract

```
## Graph context (depth=2, around=document#1)

### Objects
- document#1 (document): {...canonical JSON of o.data...}
- claim#2 (claim): {...}

### Relations
- claim#2 --supports--> document#1

### Recent events
- evt_017 object.created document#1
- evt_018 relation.created claim#2 --supports--> document#1
```

Object data is serialized with `json.dumps(sort_keys=True)` so byte-
stability holds. Empty sections render as `- (none)`. Snapshot-tested
in `tests/test_llm_prompt.py`. Changing the format is a breaking
change.

## v0.6 #14. Trace format addition for LLM events

```
[llm.requested]           evt_NNN  <behavior>  model=<m> tokens_in~NNN budget_remaining=$X.XXX
[llm.responded]           evt_NNN  <behavior>  tokens_in=NNN tokens_out=NN cost=$X.XXX latency=X.Xs
```

- `~` prefix marks estimates; bare numbers are actuals.
- `tokens_in~` and `budget_remaining=$...` are omitted when no
  `max_cost_usd` is set (no pre-call estimate happened).
- Cache hits render with `cache_hit=true` and omit `cost`/`latency`.

Snapshot-tested in `tests/test_llm_trace_snapshot.py`. v0 and v0.5
snapshot tests stay green.

## v0.6 #15. Provenance gets `llm_request_event_id`

Objects, relations, and patches created inside an `@llm_behavior`
handler carry `provenance.llm_request_event_id` pointing at the
`llm.requested` event that produced them. Auto-stamped by the
runtime via `BehaviorGraph._llm_request_event_id`; behaviors cannot
set it. Absent on objects/relations/patches created outside an LLM
handler (CONTRACT #5 stays backward-compatible).

`trace.causal_chain(object_id)` walks through this link first when
present, rendering the LLM round-trip (`llm.requested` with model,
`llm.responded` with cost or `cache_hit`) before continuing up the
`caused_by` chain.

## v0.6 #16. The killer demo is `examples/llm_claim_extraction.py`

Written first, locked the API. Three documents, structured-output
extraction, a low-confidence flag, a relation behavior tagging
source docs, a cached fork with `replay_llm_cache=True`, and a
causal chain that crosses the LLM boundary. Integration-tested in
`tests/test_llm_claim_extraction.py`.

## v0.6 #17. Backward compatibility

All v0 and v0.5 tests pass unchanged. `Runtime(graph)` without
`llm_provider=` works exactly as before — the new
`MissingProviderError` only fires at `_ensure_registry()` time when
an `@llm_behavior` is in the registry but no provider was passed.
v0/v0.5 trace snapshots stay byte-identical.

## v0.6 #18. Fork re-queues unfired events (extension of v0.5 #8)

In v0.5, `_requeue_unfired` ran only on `Runtime.load`. v0.6 extends
it to `runtime.fork` too — without it, forking at an early event
(e.g. `goal.created`) followed by `run_until_idle` would be a no-op
because no downstream behaviors had a chance to fire on the seed
event. The invariant from v0.5 diff #8 (single-threaded loop, no
partial fanout) still holds; behavior here is the natural
generalization.

## v0.6 #19. Out of scope

- Streaming responses (v0.7+)
- Tool use / function calling inside LLM behaviors (v0.7, separate primitive)
- Multi-model routing / fallback (v0.7+)
- Prompt caching as a first-class concern (v1+; we don't actively
  fight it but the cache key includes everything that affects
  output, so we don't get free cross-call sharing either)
- Cypher pattern subscriptions (v0.7)
- Packs (v1.0)

If a v0.6 PR drifts toward any of these, reject.

## v0.6 #20. API-first development

`examples/llm_claim_extraction.py` was written before any of the LLM
runtime existed. Same discipline as v0 #17 and v0.5 #20.

## v0.6 #21. Tests don't hit the live API

CI runs the suite without `ANTHROPIC_API_KEY` and never makes a real
call. `tests/_llm_helpers.py` provides `ScriptedProvider` and
`FailingProvider`; `tests/test_llm_anthropic.py` mocks the SDK
client. `RecordedLLMProvider` is the production fixture path.

## v0.6 #22. KNOWN LIMITATION (narrowed, not closed): replay payload drift

v0.5 #7's known limitation said replay-strict catches categorical
non-determinism (different event types, different counts) but not
payload-only drift. v0.6 narrows the gap on both axes:

- **Event-type stream check** stays in force (v0.5 #7).
- **Prompt-hash check** is added (v0.6 #8 DIFF): the runtime detects
  divergence at prompt-construction time, pinned to the offending
  `llm.requested` event id. This catches drift from non-deterministic
  view assembly, frame mutation between runs, schema rebuilds, etc.

What remains best-effort:

- **Provider-side response drift.** Anthropic's messages API has no
  seed parameter, so even with `temperature=0` two identical calls
  are not guaranteed to be bit-identical. The replay cache works
  around this in practice (forks read cached responses, not fresh
  calls), but `replay_strict=True` against a run that lacks cached
  responses for every LLM call still cannot catch sub-prompt drift.

The honest framing: drift is now detected at prompt-construction
time; provider-side response drift remains best-effort. Revisits
with v0.7 multi-provider routing, when the question becomes
unavoidable.

---

# Active Graph v0.7 — Tools + advanced matching addendum

v0.7 makes tool use a first-class primitive (not buried inside LLM
behaviors) and lands Cypher-style pattern subscriptions plus
event-count temporal predicates. The two are bundled because they
share a hard problem: non-determinism the runtime didn't cause. A
tool call hits an external system whose response can change between
runs; a pattern subscription fires based on graph shape that depends
on past behavior. Both stress the replay and audit guarantees in
similar ways. Solving them together produces a coherent v0.7.
v0/v0.5/v0.6 decisions all remain in force; the items below are
additions and a handful of explicit narrowings.

## v0.7 #1. Tools are not LLM behaviors

Tools are a primitive. `@tool` registers a callable with metadata and
schemas; the runtime invokes them via an event pair
(`tool.requested` / `tool.responded`) the same way LLM calls flow
through `llm.requested` / `llm.responded`. An LLM behavior that uses
tools is composing two primitives: an LLM call and one or more tool
calls. The runtime orchestrates the loop between them. This is what
keeps tool-using behaviors auditable.

## v0.7 #2. `@tool` and the global tool registry

```python
@tool(
    name="web_fetch",
    description="...",
    input_schema=WebFetchInput,
    output_schema=WebFetchOutput,
    cost_per_call=Decimal("0.001"),
    timeout_seconds=10.0,
    deterministic=False,
)
def web_fetch(args, ctx): ...
```

Decorator pushes into a module-level `_TOOL_REGISTRY` parallel to the
behavior registry. Tests call `clear_tool_registry()`. `Runtime(graph,
tools=[...])` overrides the global registry, mirroring `behaviors=[...]`.
Each LLM behavior's `tools=[t1, t2, ...]` is resolved at startup;
missing tools raise `MissingToolError` at `_ensure_registry()` time.

`Tool.fn(args: InputSchema, ctx: ToolContext) -> OutputSchema` is the
signature. Inputs are validated before invocation; outputs after.
Mismatches map to `tool.invalid_input` / `tool.invalid_output`.

## v0.7 #3. Tool invocation is an event pair

`tool.requested` payload: `behavior`, `tool`, `args_hash`, `args`
(canonicalized), `call_id` (LLM-provided), `cache_hit`,
`deterministic`. `tool.responded` payload: same plus `output`,
`error` (None on success, `{reason, message, ...}` on failure),
`latency_seconds`, `cost_usd`. Cache key:
`sha256(canonical_json({tool_name, args_normalized}))`.
Args normalization: Pydantic models → `model_dump(mode="json")`,
Decimal → str, dicts sorted by key at JSON-dump time.

## v0.7 #4. LLM ↔ tool turn loop is the runtime's job

When an `@llm_behavior` declares `tools=[...]`, the runtime owns the
multi-turn loop:

1. Call LLM with tools in the request
2. If response carries `tool_calls`, dispatch each: emit
   `tool.requested`, invoke, emit `tool.responded`, append result as
   `role="tool"` message
3. Re-call LLM
4. Repeat until non-tool response or `max_tool_turns` (default 6) hits

The handler signature stays `(event, graph, ctx, llm_output) -> None`.
Handler sees only the final parsed output — never raw tool calls.

`LLMMessage` gains `role="tool"` and `tool_use_id` + `tool_name`
fields so providers can echo results back. `LLMResponse` gains
`tool_calls: Optional[list[ToolCall]]`. `LLMProvider.complete()` gains
`tools: Optional[list[dict]] = None`. All backward-compatible: omitted
defaults preserve v0.6 behavior.

## v0.7 #5. Tool context is restricted

```python
@dataclass
class ToolContext:
    behavior_name: str
    event_id: str
    frame: Optional[Frame]
    idempotency_key: str
    timeout_seconds: float
    logger: logging.Logger
```

NO graph reference. Tools that need graph read access close over a
`Graph` via a factory — see `make_graph_query_tool(graph)`. The
constraint is intentional: tools that touch the graph should be
obvious, not ambient. `idempotency_key` is an opaque pass-through:
tool authors forward it to external APIs that support idempotency
tokens; the runtime never uses it for dedupe (that's the cache's job).

Tools cannot mutate the graph directly. If a tool wants to record
information, it returns it in its output and the calling behavior's
handler writes the mutation. Same constraint as `BehaviorGraph` for
behaviors: actions are explicit, mutations are auditable.

## v0.7 #6. Tool failure modes are structured

Mirror of v0.6 #11. `ToolError(reason, message, payload_extras)` is
the carrier; the runtime maps it into `tool.responded.error` AND
`behavior.failed.reason`. Codes:

- `tool.timeout` — exceeded `timeout_seconds`
- `tool.network_error` — provider / network failure
- `tool.invalid_input` — input schema validation failed
- `tool.invalid_output` — output schema validation failed
- `tool.execution_error` — tool function raised
- `tool.unknown_tool` — LLM asked for a tool the behavior didn't declare
- `tool.fixture_missing` — `RecordedToolProvider` had no fixture
- `tool.max_turns_exhausted` — exceeded `max_tool_turns`
- `budget.tool_calls_exhausted` — would exceed `max_tool_calls`
- `budget.cost_exhausted` — tool cost would exceed `max_cost_usd`

No silent retries. If a developer wants retry behavior, they subscribe
to `behavior.failed`.

## v0.7 #7. Tool determinism — DECISION: serve-from-cache by default

**Locked decision (per push-back exchange):**

ALL tools (deterministic or not) serve from cache by default on
replay. The opt-in `Runtime(replay_reinvoke_deterministic=True)`
flag is what actually lets deterministic tools re-invoke during
replay.

The reasoning: even a deterministic tool's correctness depends on
the reconstructed graph state matching the recorded state at the
moment of the call. The runtime cannot cheaply verify that without
doing essentially the same work as the cache lookup. Cheaper and
more honest to cache-by-default; `replay_reinvoke_deterministic`
stays available for the "would this still hold?" workflow.

A divergent prior event poisons every deterministic-tool call after
it — by serving from cache by default we localize the failure to a
visible cache mismatch rather than a silent re-invocation against
wrong inputs.

## v0.7 #8. Cypher subset — LOCKED grammar

A strict subset, refused with `UnsupportedPatternError` pointing at
the offending token. The full subset:

**Supported**:
- Node patterns: `(var:type {prop: value})` — properties are EQUALITY ONLY
- Relationships: `(a)-[var:rel_type]->(b)` and `(a)<-[var:rel_type]-(b)`
- Multi-hop linear chains: `(a)-[:r1]->(b)-[:r2]->(c)`
- WHERE clauses with `AND` and `NOT`
- `NOT EXISTS { sub_match }`
- Property access: `a.confidence > 0.7` (auto-routes through `a.data.<field>`)
- Comparison operators: `=`, `<`, `>`, `<=`, `>=`, `!=`, `<>`
- Literals: int, float, string (single or double quoted), `TRUE`,
  `FALSE`, `NULL`
- Relationship variable binding `[r:type]` — included per push-back
  exchange because it's cheap and a contradiction-handler that wants
  to delete the relation needs it

**Refused** (with token-pinned error):
- `OR` in WHERE — register two behaviors instead. Disjunction makes
  matchers either back-track or eval-both-paths; register-two is
  cleaner.
- `RETURN` — patterns produce bindings via `ctx.matches`, not via a
  RETURN clause; precise parser error saves an hour of confusion
- `OPTIONAL MATCH`, `WITH`, `UNION`, `UNWIND`, `MERGE`, `CREATE`,
  `SET`, `DELETE`, `DETACH`, `REMOVE`, `FOREACH`, `CALL`, `LIMIT`,
  `SKIP`, `ORDER`
- Variable-length paths (`-[*]-`)
- Aggregation
- Subqueries beyond `NOT EXISTS`
- Undirected edges (`(a)-[:r]-(b)`) — use a directed shape
- Edges without a type (`(a)-[]->(b)`)
- Node `{prop: value}` with non-literal values — comparisons go in WHERE

## v0.7 #9. Pattern compilation happens at registration

The decorator parses + compiles immediately. Invalid syntax fails at
import time, not at runtime. The compiled `PatternMatcher` is stored
on the behavior dataclass; `runtime.Registry.match()` calls
`matcher.matches(event, graph)` on every dispatch.

## v0.7 #10. Pattern evaluation bound — DECISION: live-only

Wall-clock budgets on replay produce spurious divergence on slower
CI. Pattern-evaluation budgets are enforced live only, skipped on
replay. This matches how any timeout should be handled on replay —
replay is not subject to live-time constraints because the events
already happened. v0.7 does not actually ship a configurable
`max_pattern_evaluation_ms` knob; instead, evaluation is bounded by
the natural graph size and complexity. If pattern evaluation becomes
an actual bottleneck before v1, we add the knob (and document it as
live-only).

## v0.7 #11. Behaviors can mix event-type and pattern subscriptions

With both `on=[...]` and `pattern=...`, BOTH must hold. Pattern-only
behaviors (no `on=`) check every non-lifecycle event. Lifecycle
events (`behavior.*`, `relation_behavior.*`, `runtime.*`, `llm.*`,
`tool.*`, `pattern.*`) are excluded from pattern-only checks —
otherwise patterns would re-fire endlessly on their own scheduling
events.

Either-or semantics? Register two behaviors. Don't add OR to the
pattern grammar.

## v0.7 #12. Pattern matches are passed via `ctx.matches`

`ctx.matches: list[Match]` where each `Match` binds variable names to
object ids (for nodes) or relation ids (for `[r:type]` rels). Empty
list for behaviors without a pattern. **Fire-once-per-event**, not
once per match — iterating bindings is the developer's job.

## v0.7 #13. `activate_after` — LOCKED: event-count only

```python
@behavior(on=["object.created"], activate_after=2)        # int
@behavior(on=["object.created"], activate_after="2 events")  # string form
```

Per the push-back exchange: event-count only for v0.7. Wall-clock
delays drag in a clock-source abstraction (full subsystem), break
determinism under replay, and change nothing about the demos.
Event-count composes with the tick model and replays for free.

Wall-clock unit strings (`"5 minutes"`, `"2 seconds"`, etc.) raise
`ValueError` at decoration with a pointer to this contract item.

The runtime maintains a `DelayedQueue` alongside the main FIFO. On
schedule: emit `behavior.scheduled` and push an entry tagged with
`fire_at_event_count = current_tick + N`. The main loop drains the
queue first, then checks the delayed queue for due entries.

**At fire time, `where=` is re-checked against the current graph
state.** If it no longer holds, the invocation is silently skipped
(no extra event). The trace shows the original `behavior.scheduled`
without a matching `behavior.started` — sufficient evidence the
condition lapsed.

Escape hatch for wall-clock: the user calls `runtime.tick()` from
their own loop and injects `timer.fired` events on a wall-clock
schedule. v1+ extension point if anyone actually needs it.

## v0.7 #14. Tool budget integration

`max_tool_calls: int | None` added to known budget keys (already
shipped as a stub in v0.6). When a tool call would exceed, the tool
is not invoked, `behavior.failed reason="budget.tool_calls_exhausted"`
fires, the loop continues. `max_cost_usd` is shared between LLM and
tool costs — they're both dollars.

`_budget_reason()` maps internal limit names (e.g. `max_tool_calls`)
to v0.7 reason codes (`budget.tool_calls_exhausted`) so users see the
consistent vocabulary instead of internal keys.

## v0.7 #15. Recorded tool mode

`RecordedToolProvider(fixtures_dir)` reads `<tool_name>/<args_hash>.json`
and serves on hit; misses raise `ToolError(reason="tool.fixture_missing")`.
`RecordingToolProvider(inner_invoker, fixtures_dir)` wraps another
invoker and persists each response as a fixture. Use once with
`@pytest.mark.records_tools` opt-in to seed fixtures, then commit and
run thereafter against `RecordedToolProvider`.

Fixture file shape — `recorded_at` OUTSIDE the hashed body, same as
v0.6 LLM fixtures:

```json
{
  "tool":        "web_fetch",
  "args_hash":   "<sha256_hex>",
  "recorded_at": "2026-05-15T10:32:01Z",
  "args":        { ... only this contributes to the hash ... },
  "output":      { ... },
  "error":       null,
  "latency_seconds": 0.8,
  "cost_usd":    "0.001"
}
```

## v0.7 #16. Two reference tools

- `web_fetch` (`activegraph.tools.web_fetch`) — stdlib `urllib` HTTP
  GET. No third-party dependency. `deterministic=False`. Production
  use should generally wrap a real HTTP client.
- `graph_query` — built via `make_graph_query_tool(graph)` factory.
  Operates on the graph itself through the same event-sourced
  invocation path as any other tool. Marked `deterministic=True`
  (subject to the v0.7 #7 replay caveat).

`graph_query` is the demonstration that the tool primitive is
general — not just an "external API" escape hatch.

## v0.7 #17. Demo is the contract

`examples/diligence_with_tools.py` was written before any of the
v0.7 runtime existed. Same discipline as v0 #17, v0.5 #20, v0.6 #16.
The demo exercises:

- `@behavior` planner that bootstraps the run
- `@llm_behavior` `question_generator` (no tools)
- `@llm_behavior` `researcher` (tools=[web_fetch, graph_query])
- pattern-subscribed `@llm_behavior` `critic` for contradictions
- `@behavior` `nag` with `activate_after=2`
- save + fork with `replay_llm_cache=True` AND `replay_tool_cache=True`
- causal chain that crosses both LLM and tool boundaries
- two traces printed: parent with live calls, fork with all-cached

## v0.7 #18. Trace format additions

New `[...]` tags, all snapshot-tested:

```
[tool.requested]      evt_NNN  behavior  tool=name args_hash=AAA cache_hit=false deterministic=true
[tool.responded]      evt_NNN  behavior  tool=name latency=X.Xs cost=$X.XXX
[pattern.matched]     evt_NNN  behavior  matches=N
[behavior.scheduled]  evt_NNN  behavior  activate_after=N_events
```

`args_hash` is truncated to the first 8 hex chars in the trace for
readability (full hash is in the event payload). Cache hits omit
`latency` and `cost`. Tool errors render with `error=tool.<reason>`.

`[llm.requested]` gains `turn=N` (omitted for turn 0) and
`prompt_normalized=true` (the v0.6 follow-up: surfaces that
volatile-field stripping ran in prompt assembly, so when fork-cache
behavior surprises someone six months from now the trace tells them
what happened without them having to read the assembler source).

## v0.7 #19. Provenance gets `tool_request_event_ids`

When an object/relation/patch is created inside an `@llm_behavior`
handler whose turn loop invoked tools, its provenance includes
`tool_request_event_ids: list[str]` enumerating every `tool.requested`
event that contributed to the final LLM output. Auto-stamped by
`BehaviorGraph._tool_request_event_ids`; behaviors cannot set it.

`trace.causal_chain(object_id)` walks the LLM round-trip first
(`llm.requested` + `llm.responded`), then enumerates each tool
round-trip (`tool.requested` + `tool.responded`), then continues up
the `caused_by` chain to the source event. One walk: full lineage
from a claim → LLM call → every tool call → source documents → goal.

## v0.7 #20. Per-turn LLM/tool cache with ordering verification

Per push-back agreement: per-turn cache (not consolidated). The
sequence `(llm_response, tool_call, tool_response, llm_response, ...)`
is itself a small state machine. Strict-replay verifies each turn's
prompt hash against the recorded sequence; mismatch raises
`ReplayDivergenceError` pinned to the offending `llm.requested` event
id (same divergence-pinning pattern as v0.6 #8).

Per-turn keys preserve the fork-and-mutate-one-tool workflow.
Consolidated keys would lock the loop into all-or-nothing replay.

## v0.7 #21. LLM cache round-trips `tool_calls`

`LLMCache.get()` / `record()` / `from_events()` all preserve
`tool_calls` so a cached LLM response produces the same turn-loop
shape as a live one. Without this, a fork's cached first turn would
not trigger the tool re-dispatch and would fail with
`llm.parse_error`. Test coverage: `tests/test_tool_replay.py`.

## v0.7 #22. Backward compatibility

All v0 / v0.5 / v0.6 tests pass unchanged (147 of them). v0/v0.5/v0.6
trace snapshots stay byte-identical EXCEPT the v0.6 `llm.requested`
line, which gains the trailing `prompt_normalized=true` flag (the
v0.6 follow-up bundled into v0.7). The v0.6 snapshot was updated
in the same commit; the README's expected v0.6 trace block is updated
to match.

`Runtime(graph)` without `tools=` or `@tool` decorators behaves
exactly as v0.6 did. The new `MissingToolError` only fires when an
`@llm_behavior` declares a tool the runtime cannot find at startup.
`LLMProvider.complete(..., tools=None)` is the default — providers
that ignore the kwarg keep working.

## v0.7 #23. Out of scope

- Streaming LLM responses (v0.8+)
- Multi-model routing / fallback (v0.8+)
- Real-time graph subscriptions for external UIs (v1.0+)
- Distributed runtime (v1.0+)
- Packs (v1.0)
- Wall-clock `activate_after` (v1+ if anyone actually needs it)
- `OR` in pattern WHERE clauses (v1.0+ once indexing makes it cheap)
- Variable-length paths in patterns (v1.0+)
- Configurable `max_pattern_evaluation_ms` knob (added when an actual
  bottleneck shows up)
- Tool implementations beyond `web_fetch` + `graph_query`

If a v0.7 PR drifts toward any of these, reject.

## v0.7 #24. API-first

`examples/diligence_with_tools.py` was written before any of the
runtime existed. Same discipline as v0 #17, v0.5 #20, v0.6 #16.

## v0.7 #25. Tests don't hit live anything

CI runs the suite without `ANTHROPIC_API_KEY` and without network
access. No test makes a real LLM call or a real HTTP fetch.
`RecordedLLMProvider` + `RecordedToolProvider` are the production
fixture paths. The `@tool web_fetch` reference implementation uses
stdlib `urllib` so it's not a network dependency at import time, but
no test actually calls it against a URL — the demo's scripted
provider serves canned URL responses.


---

# Active Graph v0.8 — Persistence, observability, operator surface

v0.8 is the milestone where the framework stops adding capability and
starts hardening the boundary between the runtime and the world it has
to live in. Three concerns: persistence beyond SQLite (Postgres),
operator-grade observability (structured logs + metrics), and an
operator-facing CLI. Backward compatibility with v0–v0.7 is absolute.

## v0.8 #1. PostgresEventStore mirrors SQLiteEventStore

Same schema (`events`, `runs`, `meta`), same protocol, same semantics
including `UNIQUE(id, run_id)`. Postgres-native types where they
matter: `BIGSERIAL` for `seq`, `TIMESTAMPTZ` for timestamps, `JSONB`
for `payload`. Schema version is stored in `meta` and verified on
every open; a mismatch is a hard error.

The EventStore protocol is the contract. The two implementations are
interchangeable behind it. No Postgres-specific methods leak through.

## v0.8 #2. Stores are addressed by connection URL

The framework addresses stores by URL everywhere (runtime, CLI,
library APIs). The schemes follow the SQLAlchemy convention:

- `sqlite:///relative/path.db` (three slashes — relative path)
- `sqlite:////absolute/path/to/run.db` (four slashes — absolute)
- `postgres://user:pass@host:port/dbname`
- `postgresql://user:pass@host:port/dbname` (same scheme)

A URL with no scheme is rejected with a message pointing at the right
form. `activegraph inspect run.db` fails with "use sqlite:///run.db";
the framework will not silently guess. `Runtime.load(path)` accepts
either a URL or a bare SQLite path (the v0.5–v0.7 sugar form) so
existing call sites are unchanged.

`open_store(url, run_id)` is the single library entry point that
dispatches on scheme; the Postgres dependency stays optional via lazy
import.

## v0.8 #3. Connection management is the user's job

`PostgresEventStore` accepts a URL string (opens a dedicated
connection), an existing `psycopg.Connection` (the store does not own
lifecycle), or a `psycopg_pool.ConnectionPool` (the store does
`getconn` / `putconn` per operation).

The framework does NOT ship its own pool. Production users pass
`psycopg_pool.ConnectionPool` with tuning they own. This keeps the
framework's dependency surface tiny and avoids prescribing pool
parameters we are not in a position to choose.

Pinned: `psycopg>=3.1,<4`. Async is supported by psycopg 3 but the
v0.8 runtime is sync; async is a v1+ conversation.

## v0.8 #4. The event log is not queryable through the framework

JSONB is queryable in Postgres, but we do not expose
`EventStore.query_by_payload(...)`. The temptation is real; resist it.
The event log is append-only and read-sequentially from the framework's
side. Payload querying is a database concern. Users who want to run
Postgres queries against the JSONB column directly are welcome to;
the framework does not help.

## v0.8 #5. Migration is transaction-per-run, idempotent, one-directional

`activegraph migrate --from <url> --to <url>` copies runs from source
to destination with these rules:

- Each run migrates in **a single destination transaction**. A failure
  mid-run rolls that run's destination state back. The destination
  never holds a partially-written run.
- Writes are idempotent at the event level via
  `INSERT ... ON CONFLICT (id, run_id) DO NOTHING`. Re-running
  migration after a partial failure resumes safely.
- Runs migrate **independently**. A bad run does not block the others.
  The CLI prints a per-run report; `--json` emits the same data
  machine-readably.
- Migration is **one-directional**. No `sync` mode, no rollback,
  no bidirectional reconciliation. To go back, migrate the other way.

This revises the earlier "copy + verify count" design. Verify-count
without a transaction is meaningless: both sides of the comparison
are computed against the broken intermediate state. The transaction-
per-run model is strictly better and not more complex.

## v0.8 #6. Structured logging schema

Every log line is a single JSON object on one line. Fields that don't
apply are **omitted, not nulled**. The schema is the operator
contract; dashboards built against these field names keep working
across framework versions.

Schema (`LOG_FIELDS` in `activegraph/observability/logging.py`):

  timestamp, level, logger, message, run_id, event_id, behavior,
  tool, model, cache_hit, cost_usd, latency_seconds, reason,
  error_type, error_message

The framework does NOT auto-configure logging on import. By default
it logs to `logging.getLogger("activegraph")` and lets the user's
config handle output. `configure_logging(level, json_output=True,
payload_redactor=None)` is the opinionated opt-in.

Adding a field is a schema-version change. Removing or renaming a
field is a breaking change.

## v0.8 #7. Logging level discipline

DEBUG    — view construction, prompt assembly, cache lookup, queue ops.
INFO     — every event emitted, behavior invoked, tool call.
WARNING  — budget approaching limits, retries, pattern eval slowness.
ERROR    — `behavior.failed` with non-budget reasons.
CRITICAL — event log inconsistency, schema mismatch, replay divergence.

No `print()` calls anywhere in the framework. The trace printer is a
developer tool; it writes to stdout and does not log.

## v0.8 #8. Metrics protocol is three methods

    class Metrics(Protocol):
        def counter(self, name, tags, value=1.0): ...
        def histogram(self, name, tags, value): ...
        def gauge(self, name, tags, value): ...

No timers (use a histogram with a latency value). No summaries
(Prometheus-specific). No custom types. Three methods is the entire
surface custom backends implement.

Standard tag keys: `event_type`, `behavior`, `tool`, `model`,
`reason`, `run_id` (gauges only — see #C4).

## v0.8 #9. Standard metrics (operator contract)

The runtime emits this fixed set of metrics. Adding a metric is a
public API change; the table is documented in `docs/operating.md` and
test-pinned in `activegraph/observability/metrics.py::METRIC_NAMES`.

Names follow Prometheus conventions natively (`_total` for counters,
`_seconds` for duration histograms, `_usd` for currency histograms).
This avoids the `prometheus_client` silent dot-to-underscore renaming
that would otherwise make documented names diverge from exported
names.

Counters:
  activegraph_events_emitted_total{event_type}
  activegraph_behaviors_invoked_total{behavior}
  activegraph_behaviors_failed_total{behavior, reason}
  activegraph_llm_calls_total{model}
  activegraph_llm_cache_hits_total{model}
  activegraph_llm_failed_total{model, reason}
  activegraph_tools_calls_total{tool}
  activegraph_tools_cache_hits_total{tool}
  activegraph_tools_failed_total{tool, reason}
  activegraph_patterns_evaluated_total
  activegraph_replay_divergence_detected_total{reason}

Histograms:
  activegraph_behaviors_duration_seconds{behavior}
  activegraph_llm_tokens_in{model}
  activegraph_llm_tokens_out{model}
  activegraph_llm_cost_usd{model}
  activegraph_tools_duration_seconds{tool}
  activegraph_patterns_evaluation_duration_seconds

Gauges:
  activegraph_queue_depth
  activegraph_budget_cost_remaining_usd{run_id}
  activegraph_budget_events_remaining{run_id}

Note: cache hits are a **separate counter**, not a `cache_hit=true|false`
tag on the unified call counter. This lets dashboards do
`rate(cache_hits) / rate(calls)` as a one-line query instead of
filtering by tag value. Success/failure follow the same pattern —
separate counters, no `success` tag.

## v0.8 #C4. The run_id cardinality rule (locked)

> `run_id` MAY appear as a tag on **gauges of active state** (where
> cardinality is bounded by the number of concurrently active runs).
> `run_id` MUST NOT appear as a tag on **counters or histograms**.

This rule prevents the most common Prometheus operational disaster:
unbounded cardinality from per-run labels accumulating forever. The
budget gauges are the only exception, and they live only for the
duration of a run.

The rule is enforced by `validate_cardinality_rule()` which runs at
import time and in the test suite (`test_observability_metrics.py`).
Any standard metric whose tag set violates the rule fails the build.

## v0.8 #10. NoOpMetrics is the default; PrometheusMetrics is opt-in

`NoOpMetrics` does nothing — three method bodies, each a single
`return`. The runtime is fully functional without metrics.

`PrometheusMetrics` lazy-imports `prometheus_client` (opt-in dep via
`activegraph[prometheus]`). Custom backends — OpenTelemetry, Datadog,
statsd — implement the three-method protocol directly. The framework
does not ship adapters.

## v0.8 #11. runtime.status() shape

    @dataclass(frozen=True)
    class RuntimeStatus:
        run_id: str
        state: Literal["idle", "running", "stopped", "exhausted"]
        queue_depth: int
        events_processed: int
        budget: BudgetSnapshot
        frame: FrameSnapshot | None
        registered_behaviors: tuple[BehaviorInfo, ...]
        recent_events: tuple[EventSummary, ...]

`status(recent: int = 20)` — single parameter controls the tail
length. The CLI's `inspect --tail N` passes through.

State is derived **from the event log**, not from in-memory
bookkeeping. This means a freshly-loaded runtime and the runtime that
saved the log agree on state. Walk back through events: if the most
recent terminal lifecycle event is `runtime.budget_exhausted` →
`exhausted`; if it's `runtime.idle` → `idle`; otherwise `stopped`.
`running` is reserved for cross-thread observation of an in-progress
loop (single-threaded today; documented for future async use).

There is **no `last_error` field**. Errors are events; filter
`recent_events` for type `behavior.failed`, or query the event store
directly. Convenience accessors that look like the source of truth
but mean different things are bug-bait.

## v0.8 #12. The CLI is a thin wrapper around library APIs

No business logic in the CLI itself. Each subcommand parses arguments,
calls into the library, and formats output. Programmatic callers do
exactly the same things.

Subcommands:

    activegraph inspect      <url> [--run-id <id>] [--tail N] [--json]
    activegraph replay       <url> --run-id <id> [--json]
    activegraph fork         <url> --run-id <id> --at-event <id>
                                   --label <label> [--to <url>] [--json]
    activegraph diff         <url> --run-a <id> --run-b <id> [--json]
    activegraph export-trace <url> --run-id <id>
                                   [--format text|jsonl] [-o PATH]
    activegraph migrate      --from <url> --to <url>
                             [--run-id <id>] [--json]

Built with `click`. The CLI is a hard dep (`click>=8,<9`) — it is
part of the operator surface.

## v0.8 #13. CLI exit codes (locked)

  0  success
  1  generic error
  2  usage error (bad arguments, missing options — click default)
  3  not found (run id does not exist, store path does not exist)
  4  corruption (schema version mismatch, event log inconsistency)
  5  divergence (replay-strict failure)

Operators and CI systems wrap these. Changing a code is a breaking
change.

## v0.8 #14. Backward compatibility is absolute

- Every v0–v0.7 test passes unchanged.
- Trace printer output is byte-identical for non-LLM, non-tool runs
  (snapshot-tested as before).
- SQLite remains the default; Postgres is opt-in.
- Metrics default to no-op.
- Logging defaults to the user's existing config; the framework adds
  no handlers on import.
- `Runtime`, `Runtime.load`, and `runtime.save_state` accept bare
  SQLite paths exactly as in v0.5+.

The v0.8 stance on event payload schemas: **no new fields on existing
event types**. New event types are fine; mutating existing payloads
breaks every snapshot test and is a v1+ change. None are added in
v0.8.

## v0.8 #15. Logging is opt-in via configuration

A library that auto-configures logging on import is hostile to
operators who have their own setup. The framework attaches to
`logging.getLogger("activegraph")` and propagates to whatever handler
the user installed. `configure_logging(...)` is the explicit opt-in
for the documented JSON schema.

## v0.8 #16. The killer demo is the spec

`examples/operate_a_run.py` was written before any implementation.
The runtime, the CLI, and the operator guide are built backward to
make it run. The example exercises every v0.8 surface:
SQLite-backed run → status → CLI inspect → CLI fork → CLI diff →
JSONL export → optional Postgres migration. The example is
integration-tested (`tests/test_operate_example.py`); if the example
breaks, the test catches it.

## v0.8 #17. EventStoreConformance is the reusable test suite

`activegraph.store.conformance.EventStoreConformance` is a mixin
class. Concrete subclasses override `make_store(run_id)` and
`cleanup()`; the same suite runs against InMemory, SQLite, and
Postgres. Any future store implementation gets free coverage by
subclassing.

## v0.8 #18. Postgres tests are gated, never mocked

`ACTIVEGRAPH_TEST_POSTGRES_URL` env var enables the Postgres
conformance suite. Without it, the tests skip — local dev without
Docker runs the other 320+ tests unaffected. Mocking Postgres
produces false confidence; we don't.

## v0.8 #19. What v0.8 deliberately does not add

- Web UI
- HTTP server
- Real-time graph subscriptions (websockets, SSE)
- Distributed runtime
- Multi-model LLM routing
- Streaming LLM responses
- Packs (still v1.0)

Stay scoped. v0.8 is less exciting than v0.6 and v0.7 by design; it
is what makes the framework deployable.
