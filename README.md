# Active Graph Runtime

> The graph is the world. Behaviors are physics. The trace is the proof.

An event-sourced reactive graph runtime for building long-running, auditable, agentic systems. Behaviors react to a shared graph instead of talking to each other. Every change is traceable. Every run is resumable.

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

After replay, events that were sitting in the queue when the runtime
stopped (e.g. budget exhausted) are re-queued and fire on the next
`run_until_idle` / `run_goal`. Events that already had a behavior start
on them are not re-fired.

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

## LLM behaviors

LLM behaviors are first-class but opt-in.

```python
from activegraph.llm import llm_behavior

@llm_behavior(
    name="claim_extractor",
    on=["document.added"],
    model="claude-sonnet-4-6",
    output_schema={
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "confidence": {"type": "number"},
                "evidence_span": {"type": "string"}
            }
        }
    },
    creates=["claim"],
    view={"around": "event.payload.document.id", "depth": 1, "token_budget": 8000}
)
def claim_extractor(event, graph, ctx, llm_output):
    for claim in llm_output:
        graph.add_object("claim", {
            "text": claim["text"],
            "confidence": claim["confidence"],
            "evidence": [event.payload["document"]["id"]]
        })
```

The wrapper handles prompt construction (including frame goal and constraints), structured output parsing, retries, and cost accounting against the budget. If the LLM call fails, a `behavior.failed` event is emitted with the error payload — failures are visible, not silent.

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

**v0.7 — Advanced matching**

- Cypher-style pattern subscriptions
- Negation predicates
- Temporal predicates (`activate_after`)
- Priority and conflict resolution policies

**v1.0 — Packs**

- Pack format (objects + relations + behaviors + policies + prompts)
- Diligence pack
- Memory pack
- Research pack

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

---

The graph is the world. Behaviors are physics. The trace is the proof.
