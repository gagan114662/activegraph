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
