# Active Graph Runtime

> The graph is the world. Behaviors are physics. The trace is the proof.

An event-sourced reactive graph runtime for building long-running, auditable, agentic systems. Behaviors react to a shared graph instead of talking to each other. Every change is traceable. Every run is resumable.

## What v0.9 ships

The first **pack** — a bundle of object types, behaviors, tools, prompts, and policies for a specific domain — and the first reference pack: **Diligence**.

```python
from activegraph import Runtime, Graph
from activegraph.packs.diligence import pack as diligence_pack, DiligenceSettings
from activegraph.packs.diligence.fixtures import (
    RecordedDiligenceProvider, THREE_COMPANIES, company_goal,
)

rt = Runtime(
    Graph(),
    llm_provider=RecordedDiligenceProvider(companies=THREE_COMPANIES),
    persist_to="/tmp/diligence.db",
)
rt.load_pack(diligence_pack, settings=DiligenceSettings())
for company in THREE_COMPANIES:
    rt.run_goal(company_goal(company))

# Three structured memos: every claim cites evidence, contradictions surface, risks identified.
memos = [o for o in rt.graph.all_objects() if o.type == "memo"]
assert len(memos) == 3
```

The full runnable demo is [`examples/diligence_real_run.py`](examples/diligence_real_run.py). It runs in under 30 seconds without an API key, byte-for-byte reproducible. The pack format itself is documented in [`docs/guides/authoring-packs.md`](docs/guides/authoring-packs.md); the locked design decisions are in [`CONTRACT.md`](CONTRACT.md) v0.9.

For the underlying primitives (everything below packs), the v0.7-style minimal example still works:

```python
from activegraph import Graph, Runtime, behavior, relation_behavior

graph = Graph()
runtime = Runtime(graph)

@behavior(on=["goal.created"])
def planner(event, graph, ctx):
    research = graph.add_object("task", {"title": "Research market", "status": "open"})
    memo = graph.add_object("task", {"title": "Draft memo", "status": "blocked"})
    graph.add_relation(research.id, memo.id, "depends_on")

@relation_behavior(relation_type="depends_on", on=["task.completed"])
def unblock(relation, event, graph, ctx):
    if event.payload["task_id"] == relation.source:
        graph.patch_object(relation.target, {"status": "open"})

runtime.run_goal("Evaluate this startup")
runtime.print_trace()
```

## Table of contents

- [Why this exists](#why-this-exists)
- [Mental model](#mental-model)
- [Install](#install)
- [Quickstart](#quickstart)
- [Core primitives](#core-primitives)
  - [Graph](#graph)
  - [Object](#object)
  - [Relation](#relation)
  - [Event](#event)
  - [Behavior](#behavior)
  - [Relation behavior](#relation-behavior)
  - [Patch](#patch)
  - [View](#view)
  - [Frame](#frame)
  - [Policy](#policy)
  - [Runtime](#runtime)
- [Activation and matching](#activation-and-matching)
- [Patches and conflict resolution](#patches-and-conflict-resolution)
- [Provenance](#provenance)
- [Tracing](#tracing)
- [Budgets and safety](#budgets-and-safety)
- [Replay and resume](#replay-and-resume)
- [Operating in production](#operating-in-production)
- [LLM behaviors](#llm-behaviors)
- [Patterns](#patterns)
- [What this is not](#what-this-is-not)
- [Roadmap](#roadmap)

## Why this exists

Most agent frameworks coordinate through messages. Agents talk to agents. Handoffs are conversations. State lives in transcripts. That works for demos and breaks for everything else: long-running diligence, evolving memory, multi-session research, anything that needs to be paused, inspected, forked, or defended.

Active Graph takes a different position. Coordination is not a conversation. It is a graph that changes.

- Objects are things in the world: claims, tasks, evidence, artifacts.
- Relations are typed edges that carry meaning, not just structure.
- Events are an append-only history of every change.
- Behaviors react to events and mutate the graph.
- Patches are proposed mutations with provenance and approval state.

The graph is the shared substrate. Behaviors coordinate by reading and writing typed state. The event log makes the entire run replayable, resumable, and auditable.

If chat-based agents are a group conversation, Active Graph is a shared workspace where everyone can see what changed, who changed it, and why.

## Mental model

```
Graph        = world
Object       = thing in the world
Relation     = typed connection between things
Event        = history of what happened
Behavior     = reaction to change
Relation     = behavior attached to an edge
Patch        = proposed state change with provenance
View         = scoped slice of the graph
Frame        = mission context for a run
Policy       = what each behavior is allowed to do
Runtime      = the engine that runs the loop
```

A behavior is just one kind of reactor. It can be a deterministic rule, an LLM call, a tool invocation, a validator, or a human approval step. Not every behavior is an agent. Most should not be.

## Install

```
pip install activegraph
```

Python 3.10+. Zero required dependencies for the core runtime. LLM behaviors and persistence are opt-in extras.

```
pip install "activegraph[llm]"      # LLM behavior helpers
pip install "activegraph[sqlite]"   # SQLite-backed event store
pip install "activegraph[all]"
```

## Quickstart

A minimal end-to-end run: goal in, graph out, trace printed.

```python
from activegraph import Graph, Runtime, behavior, relation_behavior

graph = Graph()
runtime = Runtime(graph, budget={"max_events": 200, "max_seconds": 60})

@behavior(name="planner", on=["goal.created"])
def planner(event, graph, ctx):
    goal_text = event.payload["goal"]
    research = graph.add_object("task", {"title": f"Research: {goal_text}", "status": "open"})
    memo = graph.add_object("task", {"title": "Draft memo", "status": "blocked"})
    graph.add_relation(research.id, memo.id, "depends_on")

@behavior(name="researcher", on=["object.created"], where={"object.type": "task"})
def researcher(event, graph, ctx):
    task = event.payload["object"]
    if task["data"]["status"] != "open" or "Research" not in task["data"]["title"]:
        return
    graph.add_object("claim", {
        "text": "Market appears early but growing.",
        "confidence": 0.7,
        "evidence": []
    })
    graph.emit("task.completed", {"task_id": task["id"]})

@relation_behavior(name="unblock", relation_type="depends_on", on=["task.completed"])
def unblock(relation, event, graph, ctx):
    if event.payload["task_id"] == relation.source:
        graph.patch_object(relation.target, {"status": "open"})

runtime.run_goal("Evaluate this startup idea")
runtime.print_trace()
runtime.print_graph()
```

Expected trace:

```
[goal.created]            user: "Evaluate this startup idea"
[behavior.started]        planner
[object.created]          task#1 "Research: Evaluate this startup idea" (open)
[object.created]          task#2 "Draft memo" (blocked)
[relation.created]        task#1 --depends_on--> task#2
[behavior.completed]      planner (2 objects, 1 relation)
[behavior.started]        researcher  (matched object.created: task#1)
[object.created]          claim#3 "Market appears early but growing."
[event.emitted]           task.completed task_id=task#1
[behavior.completed]      researcher
[behavior.started]        researcher  (matched object.created: task#2)
[behavior.completed]      researcher
[relation_behavior.started] unblock  (matched task.completed on depends_on edge)
[patch.applied]           task#2 status: blocked -> open
[behavior.completed]      unblock
[runtime.idle]            queue empty, budget remaining
```

## Core primitives

### Graph

The graph holds objects and relations. It is the shared state every behavior reads and writes.

```python
graph = Graph()

obj = graph.add_object(type="task", data={"title": "Research", "status": "open"})
rel = graph.add_relation(source=obj.id, target=other.id, type="depends_on", data={})

graph.get_object(obj.id)
graph.get_relations(object_id=obj.id, type="depends_on", direction="outgoing")
graph.neighborhood(obj.id, depth=2)
graph.query(object_type="claim", where={"confidence": {">": 0.8}})
```

Two important constraints:

1. Graph mutations always produce events. `add_object` emits `object.created`. `patch_object` emits `object.updated`. There is no silent state change.
2. Direct mutation is fine for low-trust state. High-trust state goes through patches. See [Patches](#patch).

### Object

Objects are typed nodes. Type is a string, data is a dict. Common types in a basic pack:

`goal`, `task`, `claim`, `evidence`, `artifact`, `critique`, `decision`, `memory`, `person`, `company`, `document`.

Every object carries provenance automatically: `created_by`, `created_at`, `created_from_event`, `evidence_refs`.

### Relation

Relations are typed directed edges. The type carries meaning and determines which relation behaviors activate.

Common relation types:

`depends_on`, `supports`, `contradicts`, `references`, `derived_from`, `assigned_to`, `requires_evidence`, `blocks`, `summarizes`, `updates`.

Relations can be passive (metadata only), rule-based (deterministic behavior), or agentic (LLM-backed). Most should be passive. Promote to behavioral only when coordination logic belongs on the edge.

### Event

Events are append-only records of everything that happened.

```python
Event(
    id="evt_017",
    type="goal.created",
    actor="user",
    payload={"goal": "Evaluate this startup"},
    frame_id="frame_001",
    caused_by=None,
    timestamp="2026-05-15T10:32:01Z"
)
```

Standard event types:

`goal.created`, `object.created`, `object.updated`, `relation.created`, `relation.removed`, `task.created`, `task.completed`, `claim.created`, `artifact.created`, `critique.created`, `patch.proposed`, `patch.approved`, `patch.rejected`, `patch.applied`, `behavior.started`, `behavior.completed`, `behavior.failed`.

You can emit custom event types. Behaviors subscribe by exact match or pattern.

### Behavior

A behavior reacts to events. It can create objects, create relations, propose patches, call tools, or emit further events.

```python
@behavior(
    name="critic",
    on=["object.created"],
    where={"object.type": "claim"},
    creates=["critique"],
    budget={"max_calls_per_run": 20}
)
def critic(event, graph, ctx):
    claim = event.payload["object"]
    if claim["data"]["confidence"] < 0.5:
        graph.add_object("critique", {
            "target": claim["id"],
            "reason": "Low confidence claim lacks evidence."
        })
```

Behavior signature: `(event, graph, ctx) -> None`. The `ctx` carries the active frame, the scoped view, the policy, and helpers for emitting events and proposing patches.

Behaviors can be:

- Function-based (`@behavior`)
- Class-based (subclass `Behavior` for stateful behaviors)
- LLM-backed (`@llm_behavior`, see [LLM behaviors](#llm-behaviors))
- Human-approval (`@human_behavior`, blocks pending review)

### Relation behavior

The differentiated primitive. Edges with logic.

```python
@relation_behavior(
    name="evidence_requester",
    relation_type="requires_evidence",
    on=["object.created"]
)
def evidence_requester(relation, event, graph, ctx):
    if event.payload["object"]["id"] == relation.source:
        graph.add_object("task", {
            "title": f"Find evidence for {relation.source}",
            "status": "open",
            "for": relation.source
        })
```

A relation behavior receives the edge plus the triggering event. It activates only for events that touch the edge's source or target.

Use a relation behavior when the coordination logic semantically belongs to the relationship, not to either endpoint. `depends_on` unblocking a target, `contradicts` triggering review, `summarizes` synthesizing an artifact — all live cleanly on the edge.

### Patch

A patch is a proposed mutation with provenance.

```python
patch = graph.propose_patch(
    target="object:memory_123",
    op="update",
    value={"summary": "User prefers graph-native architectures."},
    proposed_by="memory_behavior",
    evidence=["event_017", "claim_042"],
    rationale="User stated preference twice across two sessions."
)
```

Patch lifecycle: `proposed → approved → applied`, or `proposed → rejected`.

Default policy:

- Low-risk graph additions (new tasks, claims, critiques) auto-apply.
- Updates to memory, decisions, and external-facing artifacts go through `proposed`.
- External actions (sending email, calling APIs) always require explicit approval.

See [Patches and conflict resolution](#patches-and-conflict-resolution).

### View

Behaviors do not see the whole graph. They receive a scoped view.

```python
ctx.view  # constructed by the runtime before behavior invocation
```

View construction is driven by the behavior's declaration:

```python
@behavior(
    on=["claim.created"],
    view={
        "around": "event.payload.object.id",
        "depth": 2,
        "include_types": ["claim", "evidence", "critique"],
        "recent_events": 20,
        "token_budget": 4000
    }
)
def critic(event, graph, ctx):
    relevant_claims = ctx.view.objects(type="claim")
    recent = ctx.view.events()
```

Views prevent context bloat for LLM behaviors and reduce prompt injection surface by excluding untrusted nodes.

### Frame

A frame is the mission context for a run. It prevents drift across many behavior invocations.

```python
Frame(
    id="frame_001",
    goal="Evaluate whether this startup is fundable",
    constraints=[
        "Be concise.",
        "Separate claims from evidence.",
        "Surface risks, do not bury them."
    ],
    success_criteria=[
        "Market claims exist with evidence",
        "Risks identified",
        "Memo drafted",
        "Critic reviewed memo"
    ],
    permissions=["web_search", "memory_read"]
)
```

Every behavior receives the active frame via `ctx.frame`. LLM behaviors should include the frame goal and constraints in their prompt by default.

### Policy

Policy controls what each behavior can do.

```python
Policy(
    behavior="memory_behavior",
    can_create=["memory_candidate"],
    can_create_relation=["references"],
    can_propose=["memory_update"],
    can_apply=[],
    can_call_tool=["embed", "retrieve"],
    requires_approval=["memory_update"]
)
```

Defaults are conservative. Behaviors must declare what they need; the runtime enforces it.

### Runtime

The runtime coordinates everything.

```python
runtime = Runtime(
    graph,
    behaviors=[planner, researcher, critic, unblock],
    frame=my_frame,
    budget={
        "max_events": 500,
        "max_behavior_calls": 200,
        "max_llm_calls": 50,
        "max_seconds": 300,
        "max_depth": 25
    }
)

runtime.run_goal("Evaluate this startup")
runtime.run_until_idle()
runtime.run_until(predicate=lambda g: g.has_object_of_type("artifact"))
```

The runtime loop:

```
while queue and budget.remaining():
    event = queue.pop()
    graph.append_event(event)
    behaviors = registry.match(event, graph)
    for behavior in behaviors:
        view = build_view(behavior, event, graph)
        ctx = build_context(behavior, event, view, frame, policy)
        result = behavior.run(event, graph, ctx)
        handle_result(result)
```

## Activation and matching

Matching is the heart of the runtime. Behaviors subscribe with three layers of selectivity:

**1. Event type**

```python
@behavior(on=["object.created", "object.updated"])
```

**2. Predicate filter (`where`)**

```python
@behavior(on=["object.created"], where={"object.type": "claim", "object.data.confidence": {">": 0.5}})
```

**3. Graph pattern (advanced)**

```python
@behavior(
    on=["object.created"],
    pattern="""
        (claim:claim) -[:contradicts]-> (other:claim)
        WHERE claim.confidence > 0.7 AND other.confidence > 0.7
    """
)
```

Pattern subscriptions let you activate when graph shapes appear, not just when events fire. This is essential for behaviors like "review when two high-confidence claims contradict each other" — a condition that no single event signals.

**Conflict resolution.** When multiple behaviors match one event, the runtime invokes them in declared priority order. Behaviors are isolated: one behavior's graph mutations are visible to the next, but only via the event queue, not via shared mutable view state.

**Negation and temporal predicates.** Supported via pattern subscriptions:

```python
@behavior(
    on=["object.created"],
    pattern="(artifact:artifact) WHERE NOT EXISTS (critique)-[:targets]->(artifact)"
)

@behavior(
    on=["task.created"],
    activate_after="5 minutes",
    where={"object.data.status": "open"}
)
```

## Patches and conflict resolution

Two behaviors may propose conflicting changes to the same object. The runtime resolves with optimistic concurrency:

1. Each proposed patch records the object version it was generated against.
2. On apply, if the object version has changed, the patch is rejected and the proposer receives a `patch.rejected` event with the current version.
3. The proposer can retry by re-reading, re-reasoning, and re-proposing — or give up.

This means: no silent overwrites, no last-write-wins, no CRDT complexity. Proposers that care about a change must observe the rejection and respond.

Patch operations:

- `create` — add a new object or relation
- `update` — modify object data (merge semantics by default)
- `replace` — overwrite object data wholesale
- `remove` — delete an object or relation (always requires approval)

Auto-apply versus proposed is governed by policy. Default split:

| Operation                              | Default    |
|----------------------------------------|------------|
| Create object (claim, task, critique)  | Auto-apply |
| Update object (status, derived fields) | Auto-apply |
| Update memory                          | Proposed   |
| Replace artifact (final memo, decision)| Proposed   |
| Remove anything                        | Proposed   |
| External action (email, API call)      | Proposed   |

## Provenance

Every object, relation, and patch carries provenance automatically:

```json
{
    "id": "claim_042",
    "type": "claim",
    "data": {},
    "provenance": {
        "created_by": "researcher",
        "created_at": "2026-05-15T10:35:14Z",
        "caused_by_event": "evt_017",
        "frame_id": "frame_001",
        "evidence": ["document_003", "claim_038"],
        "confidence": 0.7,
        "method": "llm_extraction"
    }
}
```

This is non-optional. Auditable agents require it. The trace printer renders provenance inline.

## Tracing

The trace is a first-class output of every run.

```python
runtime.print_trace()
runtime.export_trace(path="run.jsonl")
runtime.trace.causal_chain(object_id="memo_001")
```

The causal chain query is the audit tool. It walks backward from any object through the events and behaviors that produced it, terminating at the originating goal.

```
memo_001 (artifact)
  ← synthesized_by synthesizer (evt_104)
  ← reviewed_by critic (evt_098)
  ← claim_042 (supports)
      ← researcher (evt_073)
      ← evidence: document_003
  ← claim_055 (supports)
      ← researcher (evt_081)
      ← evidence: document_007
  ← goal_001 "Evaluate this startup" (evt_001)
```

## Budgets and safety

Every run has hard budgets:

```python
budget = {
    "max_events": 500,
    "max_behavior_calls": 200,
    "max_llm_calls": 50,
    "max_tool_calls": 30,
    "max_patches": 100,
    "max_depth": 25,           # max causal chain depth
    "max_seconds": 300,
    "max_cost_usd": 5.00
}
```

When a budget is hit, the runtime stops gracefully, emits `runtime.budget_exhausted`, and leaves the graph in a consistent state. Resumable.

## Replay and resume

The event log is the source of truth. Every state change is appended, so
runs can be paused, reopened, branched, and compared.

### Persistence

```python
from activegraph import Graph, Runtime

graph = Graph()
runtime = Runtime(graph, persist_to="run.db")
runtime.run_goal("Evaluate this startup")
runtime.save_state()
```

`persist_to=PATH` attaches a SQLite-backed event store. Every emitted event
is appended as it happens; `save_state()` is an explicit flush. Pass nothing
to `save_state(path="run.db")` later if you want to keep the run in memory
until you decide to durable-write it.

### Resume

```python
runtime = Runtime.load("run.db")          # most recent run in the file
runtime = Runtime.load("run.db", run_id=...)
runtime.run_until_idle()
```

`Runtime.load` opens the file, picks a run (`run_id` or most-recent),
replays the event log into a fresh `Graph`, and returns a runtime ready to
continue. Behaviors are code, not state — re-register them (e.g. import
the module that defines them) before loading.

The trace marks replayed events distinctly so you can see the load
boundary:

```
[replay.event]            evt_017 object.created task#1
[replay.event]            evt_018 ...
[replay.complete]         73 events replayed, graph reconstructed
[runtime.idle]            ready to resume
```

### Queue recovery on load

When the runtime stops (budget exhausted, deliberate pause, process
crash), there may be events that were already emitted but not yet
popped from the queue. On load, those events are detected — any event
that has no `behavior.started` referencing it in the log — and pushed
back into the queue so they fire on the next `run_until_idle` /
`run_goal`. Events that already had a behavior start on them are not
re-fired.

**Caveat (in-flight loss):** if a behavior was *mid-execution* when the
runtime died (`behavior.started` emitted but no `behavior.completed` /
`behavior.failed`), its post-crash work is lost unless it had already
emitted events. Transactional behavior execution is a v1+ feature.

### Fork

```python
fork = runtime.fork(at_event="evt_073", label="alternative-thesis")
fork.graph.add_object("claim", {"text": "Counter-hypothesis", "confidence": 0.6})
fork.run_until_idle()
fork.save_state()
```

Fork allocates a new `run_id`, copies the parent's event log up to and
including `at_event` into the new run, and returns an independent runtime.
The parent is untouched. Forks-of-forks work the same way.

### Diff

```python
diff = runtime.diff(fork)
diff.shared_events            # prefix common to both runs
diff.parent_only_events       # what only happened in the parent
diff.fork_only_events
diff.divergent_objects        # objects that differ or only exist on one side
diff.divergent_relations
```

Diff is structural — divergent objects, relations, and event partitions.
Lifecycle events (`behavior.*`, `runtime.*`) are excluded from the event
partition so the signal is the run's actual history, not scaffolding.
Semantic comparison (does this claim *mean* the same thing as that one?)
is a behavior's job, not the runtime's.

### Storage details

- Backend: SQLite. The schema is two tables (`events`, `runs`) plus a
  `meta` table that pins the schema version from day one.
- `events.payload` is JSON. Decimals serialize as strings, datetimes as
  ISO 8601, sets as sorted lists. Anything non-serializable raises
  `NonSerializableEventError` at emit time, never at save time.
- One file can hold many runs. Each fork is a new run row.
- ULID `run_id`s; in-run ids (`evt_017`, `task#1`) stay the short
  human-readable forms and are reused across forks — `task#5` in a fork
  is a different object than `task#5` in the parent, scoped by `run_id`.

See `examples/resume_and_fork.py` for the end-to-end demo: start, pause,
reload in a fresh process, fork, inject a counter-hypothesis, diff.

Forking is uniquely cheap on an event-sourced graph and is one of the
strongest reasons to use this runtime over a chat-based framework.

## Operating in production

v0.8 adds the operator surface: structured logging, Prometheus
metrics, a `runtime.status()` introspection primitive, an
`activegraph` CLI for inspecting / forking / migrating runs, and
`PostgresEventStore` for shared-state deployments. The operator guide
([docs/guides/operating-in-production.md](docs/guides/operating-in-production.md)) is the document for people
running this as part of a system other people depend on; the
[`examples/operate_a_run.py`](examples/operate_a_run.py) demo
exercises the whole loop end-to-end.

```bash
activegraph inspect sqlite:////tmp/run.db          # status snapshot
activegraph fork    sqlite:////tmp/run.db \         # branch a run
    --run-id run_01J... --at-event evt_42 --label what-if
activegraph migrate --from sqlite:////tmp/dev.db \  # SQLite -> Postgres
                    --to   postgres://localhost/prod
```

## LLM behaviors

LLM behaviors are first-class but opt-in. The substrate keeps making sense
— every LLM call is two events in the log, every claim traces back to the
prompt and response that produced it, every fork can re-run for free against
the parent's recorded responses.

### Hello world

```python
from pydantic import BaseModel
from activegraph import Graph, Runtime, behavior, llm_behavior
from activegraph.llm import AnthropicProvider


class Claim(BaseModel):
    text: str
    confidence: float
    evidence_span: str


class ClaimList(BaseModel):
    claims: list[Claim]


@behavior(name="planner", on=["goal.created"])
def planner(event, graph, ctx):
    graph.add_object("document", {"title": "Q3 summary", "body": "..."})


@llm_behavior(
    name="claim_extractor",
    on=["object.created"],
    where={"object.type": "document"},
    description="Extract verifiable factual claims from the document.",
    model="claude-sonnet-4-5",
    output_schema=ClaimList,
    view={"around": "event.payload.object.id", "depth": 1},
    creates=["claim"],
    deterministic=True,
    budget={"max_llm_calls": 10},
)
def claim_extractor(event, graph, ctx, llm_output):
    doc_id = event.payload["object"]["id"]
    for c in llm_output.claims:
        claim = graph.add_object("claim", {
            "text": c.text,
            "confidence": c.confidence,
            "evidence_span": c.evidence_span,
        })
        graph.add_relation(claim.id, doc_id, "supports")


graph = Graph()
runtime = Runtime(graph, llm_provider=AnthropicProvider())
runtime.run_goal("Audit the document")
runtime.print_trace()
```

The runtime writes the prompt, calls the model, parses the structured
output, records the events, and stamps provenance. The developer's
handler runs only after a parsed `ClaimList` is in hand.

### The shape of the API

- The handler is `(event, graph, ctx, llm_output) -> None`. The 4th arg
  is a Pydantic instance of whatever you passed as `output_schema=`.
- The wrapper is opinionated about the prompt: every prompt is assembled
  by the runtime from four sources, in this fixed order — frame goal +
  constraints + behavior `description=` + output-schema reminder
  (system), a serialized view of the graph (objects + relations +
  recent events), the triggering event, and a one-sentence task
  derived from `creates=` and `output_schema=`.
- The view block is part of the public contract. Snapshot-tested.
- `prompt_template=` lets you reorder those four sections via Python
  `str.format` placeholders (`{system}`, `{view}`, `{event}`,
  `{instruction}`), but you can't bypass them — there is no raw
  string-concat path in user code.
- `claim_extractor.build_prompt(event, graph)` is public. Use it to
  inspect the exact bytes that would be sent — no API call needed.

### Providers

```python
from activegraph.llm import (
    AnthropicProvider,        # reference implementation
    RecordedLLMProvider,      # reads fixtures by prompt hash; tests use this
    RecordingLLMProvider,     # wraps a real provider, writes fixtures
)
```

Any object implementing the `LLMProvider` protocol works:

```python
class LLMProvider(Protocol):
    def complete(self, *, system, messages, model, max_tokens,
                 temperature, top_p, output_schema, timeout_seconds) -> LLMResponse: ...
    def estimate_cost(self, *, input_tokens, output_tokens, model) -> Decimal: ...
    def count_tokens(self, *, system, messages, model) -> int: ...
```

`AnthropicProvider` reads `ANTHROPIC_API_KEY` from the environment.
Never from code, never from a checked-in config. Install with
`pip install activegraph[llm]`.

### Determinism and best-effort replay

Pass `deterministic=True` to set `temperature=0` and `top_p=1`. The
Anthropic messages API has no `seed` parameter, so determinism is
best-effort — the runtime documents this honestly and the response's
`seed` field stays `None`. Even with determinism on, provider-side
sampling is not guaranteed bit-stable across calls.

### Failure handling — failures are first-class graph citizens

There are no silent retries and no hidden backoff. Every failure mode
emits a `behavior.failed` event with a `reason` code:

| Reason                       | When                                                    |
|------------------------------|---------------------------------------------------------|
| `llm.network_error`          | Connection error / timeout from the provider            |
| `llm.rate_limited`           | 429-shaped error; `retry_after_seconds` if available    |
| `llm.parse_error`            | Response contained no parseable JSON                    |
| `llm.schema_violation`       | JSON parsed but failed Pydantic validation              |
| `llm.fixture_missing`        | `RecordedLLMProvider` had no fixture for the prompt     |
| `budget.cost_exhausted`      | Pre-call estimate would push `max_cost_usd` over the cap|

If you want retries, write a retry behavior that subscribes to
`behavior.failed` with the appropriate `where=` filter. Retries become
first-class events, not middleware.

### Cost accounting

`budget={"max_cost_usd": "0.10"}` enforces a Decimal-precise cap.
Before each LLM call the runtime asks the provider for an input-token
count (Anthropic's official `count_tokens`), assumes the worst-case
output (`max_tokens` reservation), checks the projection against the
cap, and either lets the call proceed or fails with
`reason="budget.cost_exhausted"` — without making the API call. After
the call, the actual cost (from `usage`) replaces the estimate.

The pre-call `count_tokens` is only paid when (a) `max_cost_usd` is
set AND (b) no cached response was found. Cache-hit paths are free.
Budget-less runs are free.

### Replay and cached forks

LLM calls record two events:

- `llm.requested` — model, full prompt + params, prompt hash, estimated
  cost, deterministic flag, cache_hit flag
- `llm.responded` — raw text, parsed output, token counts, actual cost,
  latency, finish reason

Pass `replay_llm_cache=True` to `Runtime.load(...)` or `runtime.fork(...)`
to populate a content-keyed cache (`sha256(canonical_json(prompt+params))`)
from those recorded events. A fork that regenerates an identical prompt
serves it from cache — zero new API calls. A fork that diverges falls
through to the provider for the new prompts.

Combined with `replay_strict=True` the runtime additionally verifies
that the re-assembled prompt's hash matches the recorded one. A
mismatch raises `ReplayDivergenceError` pinned to the `llm.requested`
event id — the cache cannot silently paper over real drift in prompt
construction.

### Tracing

LLM calls appear in the trace alongside everything else:

```
[behavior.started]        claim_extractor  (matched object.created: document#1)
[llm.requested]           evt_006  claim_extractor  model=claude-sonnet-4-5 tokens_in~120 budget_remaining=$1.000
[llm.responded]           evt_007  claim_extractor  tokens_in=120 tokens_out=24 cost=$0.001 latency=0.5s
[object.created]          claim#2 "Sample claim."
[behavior.completed]      claim_extractor
```

`~` marks estimated token counts; bare counts are from the actual
response. Cache hits render as `cache_hit=true` and omit cost/latency.

### Causal chain crosses the LLM boundary

Objects created inside an LLM handler carry `llm_request_event_id` in
their provenance. The causal-chain walk uses it:

```
claim#3 (claim) "SMB segment grew 14% YoY in Q3."
  ← claim_extractor (evt_008) llm.requested  model=claude-sonnet-4-5
    (evt_009) llm.responded cost=$0.001
  ← claim_extractor (evt_010) object.created
    ← planner (evt_003) object.created
      ← user (evt_001) goal.created
```

One walk, full lineage: claim → LLM call (prompt + response + cost) →
source document → planner → goal.

### Tests without network access

Tests should never hit a live API. Two providers ship for this:

```python
# Reads fixtures by prompt hash from a directory.
provider = RecordedLLMProvider("tests/fixtures/llm")

# Wraps a real provider, persists every response as a fixture.
# Run once with --record to seed fixtures, then commit them.
provider = RecordingLLMProvider(AnthropicProvider(), "tests/fixtures/llm")
```

Fixtures are JSON files keyed by SHA-256 of the prompt-and-params
canonical form. `recorded_at` is stored alongside the fixture but
outside the hashed content so it doesn't perturb lookups but stays
available when fixtures drift months later.

See `examples/llm_claim_extraction.py` for the full demo — three
documents, structured-output extraction, a low-confidence flag, a
relation behavior, a cached fork, and a causal chain that crosses the
LLM boundary.

## Tool use

Tools are a primitive, not something buried inside an LLM behavior. A
tool is a registered function with an input schema, an output schema,
a determinism flag, a cost, and a timeout. The runtime invokes tools
through the same event-sourced pattern as LLM calls: every invocation
is a `tool.requested` / `tool.responded` event pair, with replay,
budgets, and provenance threaded through.

### A tool

```python
from decimal import Decimal
from pydantic import BaseModel
from activegraph import tool, ToolContext


class WebFetchInput(BaseModel):
    url: str
    timeout_seconds: float = 10.0


class WebFetchOutput(BaseModel):
    text: str
    status: int
    final_url: str


@tool(
    name="web_fetch",
    description="Fetch the body text of a URL.",
    input_schema=WebFetchInput,
    output_schema=WebFetchOutput,
    cost_per_call=Decimal("0.001"),
    timeout_seconds=10.0,
    deterministic=False,
)
def web_fetch(args: WebFetchInput, ctx: ToolContext) -> WebFetchOutput:
    ...
```

Tools receive a `ToolContext`, not the graph. Tools that need graph
read access close over a `Graph` via a factory — see
`make_graph_query_tool(graph)` for the reference implementation. Tools
cannot mutate the graph directly; if a tool wants to record
information, it returns it in its output and the calling behavior
writes the mutation.

**Pattern: closures, not threaded graph refs.** The deliberate choice
keeps the "tools cannot mutate the graph" invariant clean and avoids
exposing graph methods through `ToolContext` that don't exist on
`BehaviorGraph`. Write a factory that builds the tool over a captured
`Graph` reference, register the factory's return value, and the tool
gets the read access it needs without breaking the invariant. The
graph_query tool in `activegraph/tools/graph_query.py` is the
reference.

### An LLM behavior that uses tools

```python
@llm_behavior(
    name="researcher",
    on=["object.created"],
    where={"object.type": "question"},
    output_schema=ResearchFindings,
    tools=[web_fetch, make_graph_query_tool(graph)],
    budget={"max_tool_calls": 8},
)
def researcher(event, graph, ctx, out):
    # `out` is the final parsed ResearchFindings. The runtime ran the
    # LLM ↔ tool loop already; the handler never sees raw tool calls.
    for c in out.claims:
        graph.add_object("claim", c.model_dump())
```

The runtime orchestrates the multi-turn loop:

1. Call the LLM with the assembled prompt + tool definitions
2. If the response is a tool call, invoke the tool, append the result
   as a `role="tool"` message, re-call the LLM
3. Repeat until the model returns a non-tool response or
   `max_tool_turns` is hit
4. Hand the final parsed output to the developer's handler

### Failure modes

Tools fail loud, with structured reason codes — same shape as LLM
failures:

| Reason                          | When                                                |
|---------------------------------|-----------------------------------------------------|
| `tool.timeout`                  | exceeded `timeout_seconds`                          |
| `tool.network_error`            | provider / network failure                          |
| `tool.invalid_input`            | input schema validation failed before invocation    |
| `tool.invalid_output`           | output schema validation failed after invocation    |
| `tool.execution_error`          | tool function raised                                |
| `tool.unknown_tool`             | LLM asked for a tool the behavior didn't declare    |
| `tool.fixture_missing`          | `RecordedToolProvider` had no fixture               |
| `tool.max_turns_exhausted`      | turn loop exceeded `max_tool_turns`                 |
| `budget.tool_calls_exhausted`   | would exceed `max_tool_calls`                       |
| `budget.cost_exhausted`         | tool cost would exceed `max_cost_usd`               |

### Budget

`budget={"max_tool_calls": 8, "max_cost_usd": "0.10"}` enforces a tool
call ceiling and a Decimal-precise cost cap. Tools and LLM calls share
`max_cost_usd` — they're both dollars.

### Replay

`replay_tool_cache=True` (parallel to `replay_llm_cache=True`)
pre-populates a content-keyed cache from recorded `tool.responded`
events. Cache key is `sha256(canonical_json({tool_name, args_normalized}))`,
separately namespaced from the LLM cache.

**Default**: ALL tools (deterministic or not) serve from cache on
replay. Deterministic-tool correctness depends on the graph state at
the moment of the call matching the recorded state — the runtime
can't cheaply verify that, so cache-served is the honest default.

**Opt-in**: `replay_reinvoke_deterministic=True` actually re-invokes
deterministic tools on replay. Useful for "would this still hold?"
experiments.

### Recorded mode for tests

`RecordedToolProvider(fixtures_dir)` reads fixtures from disk;
`RecordingToolProvider(inner_invoker, fixtures_dir)` writes them.
Fixtures live at `tests/fixtures/tools/<tool_name>/<args_hash>.json`,
same shape as the v0.6 LLM fixtures with `recorded_at` outside the
hash.

## Pattern subscriptions

A behavior can declare a `pattern=` instead of (or in addition to)
`on=[...]`. The pattern is a strict Cypher subset compiled at
registration time; matches are exposed to the handler as
`ctx.matches`.

### Example

```python
@llm_behavior(
    name="critic",
    on=["relation.created"],
    where={"relation.type": "contradicts"},
    pattern="(c1:claim)-[r:contradicts]->(c2:claim) "
            "WHERE c1.confidence > 0.7 AND c2.confidence > 0.7",
    output_schema=Resolution,
)
def critic(event, graph, ctx, out):
    for match in ctx.matches:
        c1 = graph.get_object(match["c1"])
        c2 = graph.get_object(match["c2"])
        graph.add_object("resolution", {...})
```

When a behavior has both `on=` AND `pattern=`, both conditions must
hold — the event type matches AND the pattern matches the post-event
graph state. Pattern-only behaviors (no `on=`) check every
non-lifecycle event.

### The Cypher subset

Supported:
- Node patterns: `(var:type {prop: value})` (equality only)
- Relationships: `(a)-[var:rel_type]->(b)` and `(a)<-[var:rel_type]-(b)`
- Multi-hop: `(a)-[:r1]->(b)-[:r2]->(c)`
- `WHERE` with `AND`, `NOT`, `NOT EXISTS { ... }`
- Property access: `a.confidence > 0.7`

Refused (with `UnsupportedPatternError` at the offending token):
- `OR` in WHERE → register two behaviors instead
- `RETURN`, `OPTIONAL MATCH`, `WITH`, `UNION`, `MERGE`, `CREATE`,
  variable-length paths (`-[*]-`), aggregation, undirected edges,
  edges without a type

A clean subset is more useful than a fuzzy superset. If you need
something outside the subset for v0.7, file an issue.

## Temporal predicates: `activate_after`

```python
@behavior(
    on=["object.created"],
    where={"object.type": "task"},
    activate_after=2,
)
def nag(event, graph, ctx):
    ...
```

`activate_after=N` schedules the behavior for invocation `N` events
later. At schedule time the runtime emits `behavior.scheduled`. At
fire time the runtime re-checks `where=` against the current graph
state — if the condition no longer holds, the invocation is silently
skipped. Useful for "X hasn't been resolved by the time Y other things
happened" patterns.

**Event-count, not wall-clock.** v0.7 is intentionally event-count
only. Wall-clock would require a clock-source abstraction and break
determinism under replay. If you need wall-clock semantics, drive
`runtime.tick()` from your own loop and inject `timer.fired` events.

## Patterns

A few patterns that fall out of the model naturally.

**Critic loop.** Any object type can have a critic behavior that activates on creation and produces critique objects. Synthesizer behaviors read both the artifact and its critiques.

**Evidence-driven research.** A `requires_evidence` relation between a claim and a research task. The relation behavior auto-spawns research subtasks. When research completes, evidence is attached. When evidence meets confidence threshold, the original claim is marked supported.

**Memory consolidation.** A periodic behavior (`on=["runtime.tick"]`) scans recent events, proposes memory patches, and routes them through approval. Memory updates never auto-apply.

**Contradiction surfacing.** A pattern subscription on `(c1:claim) -[:contradicts]-> (c2:claim)` triggers a `decision_required` object whenever two claims contradict, regardless of which one was created last.

**Human in the loop.** A `human_behavior` blocks until a patch is approved or rejected through whatever UI you bolt on. The runtime remains responsive to other behaviors while waiting.

## What this is not

- Not a chat framework. If your problem fits in one conversation, use a chat framework.
- Not a workflow engine. Workflows model control flow. This models world state.
- Not a rules engine, exactly. Rules engines forward-chain over facts. This event-sources over a graph and supports LLM behaviors as first-class.
- Not a production database. The default store is in-memory with optional SQLite persistence. For production, plug in a graph backend.
- Not magic. Bad behaviors produce bad graphs. The runtime makes the badness inspectable, not absent.

## Roadmap

**v0 — Core runtime**

- In-memory graph, objects, relations, event log
- Function and class behaviors
- Relation behaviors
- Pattern subscriptions (event type + where filters)
- Patch system with optimistic concurrency
- Views with type and depth scoping
- Frames and policies
- Trace printing and causal chain queries
- Budgets

**v0.5 — Resumability (current)**

- Full event log persistence (SQLite, pluggable `EventStore`)
- Save and load runtime state across processes
- Replay: rebuild a graph from the log without re-firing behaviors
- Fork from any historical event into an independent run
- Structural diff between runs
- Strict-replay mode for catching non-deterministic behaviors
- Multiple runs per file; ULID `run_id`s; provenance carries `run_id`

**v0.6 — LLM integration**

- `@llm_behavior` decorator
- Structured output parsing
- Frame-aware prompt construction
- Cost accounting

**v0.7 — Tools + advanced matching**

- `@tool` decorator: tools as first-class primitives
- LLM ↔ tool turn loop owned by the runtime
- `tool.requested` / `tool.responded` events; replay cache
- `RecordedToolProvider` + `RecordingToolProvider`
- Two reference tools: `web_fetch`, `graph_query`
- Cypher subset pattern subscriptions (`pattern=`)
- Negation via `NOT EXISTS`
- Temporal predicates (`activate_after=N` events)
- Tool budgets + cost-sharing with LLM
- Causal chain crosses tool boundaries
- Trace integration for all new event types

The headline property v0.7 unlocks: **forkable, replayable,
cache-hit-by-default.** A run with N LLM calls and M tool calls can
be forked and re-run from any historical event with zero new API
calls, provided the re-run regenerates identical prompts and tool
arguments. `examples/diligence_with_tools.py` demonstrates a fork
that hits 9 cached LLM responses and 6 cached tool responses without
talking to any provider. No other agent framework can do this.

**v0.8 — Persistence beyond SQLite, observability, operator surface**

- `PostgresEventStore` behind the same `EventStore` protocol as SQLite
- Connection-URL addressing everywhere (`sqlite:///`, `postgres://`)
- `activegraph migrate` — transaction-per-run, idempotent, one-directional
- Structured JSON logging with a documented schema
- `Metrics` protocol + `NoOpMetrics` + `PrometheusMetrics`
- `runtime.status()` — frozen snapshot for introspection
- `activegraph` CLI: `inspect`, `replay`, `fork`, `diff`, `export-trace`, `migrate`
- Operator guide ([docs/guides/operating-in-production.md](docs/guides/operating-in-production.md))

**v0.9 — Pack format + Diligence pack (current)**

- `Pack` dataclass: frozen, equality by `(name, version)`
- Pack-aware decorators (`activegraph.packs.behavior`, `llm_behavior`,
  `relation_behavior`, `tool`) — identical to the user decorators but
  with no global registry side effects
- `runtime.load_pack(pack, settings=...)` — idempotent, conflict-explicit
- Object type schemas (Pydantic) enforced post-load
- Namespace prefixing: canonical strict (`diligence.claim_extractor`),
  short lookups lenient
- Settings: typed parameter injection (primary), `ctx.settings`,
  `ctx.pack_settings(name)`
- Prompt loader: TOML frontmatter, content-hashed for replay drift
- Discovery via `activegraph.packs` Python entry points
- `activegraph pack new <name>` scaffolding command
- `activegraph.packs.diligence` — production-quality reference pack:
  8 object types, 6 relation types, 7 behaviors, 3 tools, 2 policies,
  4 prompts, recorded fixtures for 3 companies, end-to-end demo
- Pack authoring guide ([docs/guides/authoring-packs.md](docs/guides/authoring-packs.md))
- Python floor raised to 3.11 (tomllib in stdlib)

**v1.0 — Additional packs and distribution**

- Memory pack
- Research pack
- Pack marketplace / signing / distribution mechanism
- Streaming LLM responses
- Multi-model routing
- Adaptive question generation (currently one-shot in Diligence)
- Contradiction resolution as an LLM behavior (currently detected only)

**Later**

- Distributed runtime
- Real-time graph subscriptions for UIs
- FalkorDB and Neo4j backends
- Tool integration framework
- Multi-frame coordination (sub-goals)

## License

MIT.

## Contributing

The core runtime should stay small and sharp. Contributions to packs, backends, and LLM integrations are especially welcome. Open an issue before large changes — the abstractions are still settling.

**Test discipline:** tests must remain deterministic. No live network calls in CI. LLM and tool tests use recorded fixtures (`RecordedLLMProvider`, `RecordedToolProvider`); HTTP tests use the scripted provider. If a contribution adds a test that would only pass with a live API key or live HTTP, it cannot land.

---

The graph is the world. Behaviors are physics. The trace is the proof.
