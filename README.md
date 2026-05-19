# Active Graph

> The graph is the world. Behaviors are physics. The trace is the proof.

An event-sourced reactive graph runtime for long-running, auditable,
agentic systems. Behaviors react to a shared graph instead of talking
to each other. Every change is traceable. Every run is resumable,
forkable, and diff-able from its event log.

If chat-based agents are a group conversation, Active Graph is a
shared workspace where everyone can see what changed, who changed
it, and why.

## Try it in 30 seconds

```bash
pip install activegraph
activegraph quickstart
```

The bundled Diligence pack runs against recorded fixtures: no API
key, no configuration, byte-deterministic output. You see what the
framework does before you read about how it does it.

Then walk the 10-minute tutorial:

```bash
activegraph quickstart --interactive
```

It scaffolds a behavior, runs it against the same fixtures, and ends
with the fork-and-diff workflow — the framework's most differentiated
capability.

## Install

```bash
pip install activegraph                    # core runtime + SQLite store + Diligence pack
pip install "activegraph[llm]"             # Anthropic provider
pip install "activegraph[postgres]"        # Postgres-backed event store
pip install "activegraph[prometheus]"      # Prometheus metrics
pip install "activegraph[all]"             # everything
```

Python 3.11+. Two hard dependencies (`click` for the CLI, `pydantic`
for the pack format); persistence backends and provider integrations
are opt-in extras.

## What you get

- **Event-sourced graph runtime.** Objects + typed relations + an
  append-only event log. Every mutation is an event; the trace is the
  audit trail.
- **Reactive behaviors as first-class.** Function, class, LLM-backed,
  or attached to typed edges (the relation-behavior primitive — edges
  with logic). Subscriptions are event type + predicate + a Cypher
  subset for graph-shape patterns.
- **Fork-and-diff.** Branch any run at any event into an independent
  fork, configure it differently, and structurally diff the result
  against the parent. Cache replay means the shared prefix doesn't
  re-execute (no new LLM calls). Most agent frameworks can't do this.
- **Packs.** A pack bundles object types, behaviors, tools, prompts,
  and policies for a specific domain. The bundled
  [Diligence pack](activegraph/packs/diligence) is the reference:
  8 object types, 7 behaviors, 3 tools, recorded fixtures.
- **Per-error reference pages.** Every error message ends with a
  `More:` link to a page that explains when it fires, why, and how to
  fix it. Catalog at [docs.activegraph.ai/reference/errors](https://docs.activegraph.ai/reference/errors/).

## Concepts at a glance

The framework's twelve primitives, in roughly the order you meet them
when reading a trace. Each links to its concept page on the doc site;
read those when you want depth on one piece.

- **Graph** — objects and typed relations forming the world the
  framework reasons about. The graph is a projection of the event log;
  every mutation is an event. [→ concepts/graph](https://docs.activegraph.ai/concepts/graph/)
- **Events** — the append-only history. Every behavior fires in
  response to events and produces more events; the trace is the
  ordered log of all of them. [→ concepts/events](https://docs.activegraph.ai/concepts/events/)
- **Behaviors** — the unit of reactive code. Function, class, or
  LLM-backed; declares what events it subscribes to and what it
  produces. The determinism contract is per-behavior. [→ concepts/behaviors](https://docs.activegraph.ai/concepts/behaviors/)
- **Relations** — typed edges between objects, with their own
  behaviors. The relation-behavior primitive — coordination logic on
  the edge, not on either endpoint — is uncommon in other agent
  frameworks. [→ concepts/relations](https://docs.activegraph.ai/concepts/relations/)
- **Patches** — proposed mutations with optimistic concurrency.
  Behaviors propose patches; the runtime applies or rejects them;
  rejections are events in their own right. [→ concepts/patches](https://docs.activegraph.ai/concepts/patches/)
- **Views** — scoped reads of the graph for behavior context. Type
  filters, depth filters, recent-event windows. Views are how
  pattern-driven behaviors see only what they need to. [→ concepts/views](https://docs.activegraph.ai/concepts/views/)
- **Frames** — bounded contexts for a run. Goal, constraints, budget,
  and the registered behaviors for this frame. A run can have one
  frame or many. [→ concepts/frames](https://docs.activegraph.ai/concepts/frames/)
- **Policies** — approval and gating for behavior capabilities. Which
  behaviors can call which tools, which mutations require human
  approval, what the runtime refuses. [→ concepts/policies](https://docs.activegraph.ai/concepts/policies/)
- **Patterns** — the Cypher subset for pattern subscriptions. Beyond
  event-type + predicate, behaviors can subscribe to graph shapes
  (claim-cited-by-evidence, task-blocks-task, …) with `NOT EXISTS`
  and temporal predicates. [→ concepts/patterns](https://docs.activegraph.ai/concepts/patterns/)
- **Replay** — re-execute a run from its event log. Strict mode
  re-fires every behavior and fails on divergence; permissive mode
  reconstructs state without re-firing. The LLM replay cache is what
  makes fork cheap. [→ concepts/replay](https://docs.activegraph.ai/concepts/replay/)
- **Forking** — branch any run at any event into an independent
  fork; structurally diff the fork against the parent. The framework's
  mechanism for hypothesis testing on agentic systems. [→ concepts/forking](https://docs.activegraph.ai/concepts/forking/)
- **Failure model** — a behavior failure is a `behavior.failed`
  event, not an exception. The audit trail captures failures as
  first-class history. Exceptions live at runtime entry points only.
  [→ concepts/failure-model](https://docs.activegraph.ai/concepts/failure-model/)

## A small example

The relation-behavior primitive — coordination logic on the edge,
not on either endpoint:

```python
from activegraph import Graph, Runtime, behavior, relation_behavior

graph = Graph()
runtime = Runtime(graph, budget={"max_events": 200, "max_seconds": 60})

@behavior(name="planner", on=["goal.created"])
def planner(event, graph, ctx):
    research = graph.add_object("task", {"title": "Research", "status": "open"})
    memo = graph.add_object("task", {"title": "Draft memo", "status": "blocked"})
    graph.add_relation(research.id, memo.id, "depends_on")

@behavior(name="researcher", on=["object.created"], where={"object.type": "task"})
def researcher(event, graph, ctx):
    task = event.payload["object"]
    if task["data"]["status"] != "open" or "Research" not in task["data"]["title"]:
        return
    graph.add_object("claim", {"text": "Market early but growing.", "confidence": 0.7})
    graph.emit("task.completed", {"task_id": task["id"]})

@relation_behavior(name="unblock", relation_type="depends_on", on=["task.completed"])
def unblock(relation, event, graph, ctx):
    if event.payload["task_id"] == relation.source:
        graph.patch_object(relation.target, {"status": "open"})

runtime.run_goal("Evaluate this startup idea")
runtime.print_trace()
```

The `unblock` relation behavior fires only for events touching one of
its edge endpoints. The conceptual deep-dive on edges-with-logic is
in [`docs/concepts/relations.md`](https://docs.activegraph.ai/concepts/relations/).

## Documentation

- **[docs.activegraph.ai](https://docs.activegraph.ai/)** — full doc site:
  concepts, guides, cookbook, CLI reference, API reference, the
  per-error catalog.
- **[10-minute tutorial](https://docs.activegraph.ai/quickstart/)** — install
  to a working custom behavior, including fork-and-diff.
- **[CHANGELOG.md](CHANGELOG.md)** — every release, with per-version
  migration notes.
- **[CONTRACT.md](CONTRACT.md)** — locked design decisions, version
  by version. Useful when you want to know *why* something is the way
  it is.
- **[examples/](examples)** — runnable end-to-end demos:
  [`diligence_real_run.py`](examples/diligence_real_run.py),
  [`resume_and_fork.py`](examples/resume_and_fork.py),
  [`llm_claim_extraction.py`](examples/llm_claim_extraction.py),
  [`diligence_with_tools.py`](examples/diligence_with_tools.py),
  [`operate_a_run.py`](examples/operate_a_run.py),
  [`babyagi.py`](examples/babyagi.py) — BabyAGI's autonomous agent loop,
  rebuilt as three reactive behaviors over a shared graph.

## What this is not

- Not a chat framework. If your problem fits in one conversation, use
  a chat framework.
- Not a workflow engine. Workflows model control flow. This models
  world state.
- Not a rules engine, exactly. Rules engines forward-chain over
  facts. This event-sources over a graph and supports LLM behaviors
  as first-class.
- Not a production graph database. The default store is SQLite,
  optionally Postgres. For a high-throughput graph backend, plug one
  in behind the `EventStore` protocol.
- Not magic. Bad behaviors produce bad graphs. The runtime makes the
  badness inspectable, not absent.

## Status

**v1.0 (stable)** (2026-05). The first-time-user gate per
[CONTRACT v1.0 #C4](CONTRACT.md#v10-c4-v10-ships-as-v10-rc1-first-time-user-gate-is-owned-externally)
ran through three rcs; v1.0 final ships rc3 plus a tutorial-step-7
output fix and a README "Concepts at a glance" index. See
[CHANGELOG.md](CHANGELOG.md) for the full v0 → v1.0 history and
per-version migration notes.

Major shipped milestones:

- **v1.0** — error hierarchy rewrite with per-error reference
  pages, doc site at [docs.activegraph.ai](https://docs.activegraph.ai/),
  `activegraph quickstart` command, mypy `--strict` and docstring
  coverage CI gates, wheel-completeness and deploy-verification CI
  gates.
- **v0.9** — pack format and the Diligence reference pack (8 object
  types, 7 behaviors, 3 tools, recorded fixtures).
- **v0.8** — operator surface: structured logging, Prometheus
  metrics, `runtime.status()`, full `activegraph` CLI,
  `PostgresEventStore`.
- **v0.7** — `@tool` decorator, Cypher-subset pattern subscriptions,
  temporal predicates.
- **v0.6** — `@llm_behavior` with structured output, frame-aware
  prompt construction, cost accounting.
- **v0.5** — full event-log persistence, save/load across processes,
  fork from any historical event, structural diff between runs.
- **v0** — core runtime: graph, behaviors, relation behaviors,
  patches with optimistic concurrency, views, frames, policies,
  budgets, the trace.

Roadmap items planned for v1.1 are tracked in
[CONTRACT.md § v1.1](CONTRACT.md).

## License

MIT.

## Contributing

The core runtime stays small and sharp. Contributions to packs,
backends, and LLM integrations are especially welcome. Open an issue
before large changes — the abstractions are still settling.

**Test discipline:** tests must remain deterministic. No live network
calls in CI. LLM and tool tests use recorded fixtures
(`RecordedLLMProvider`, `RecordedToolProvider`). If a contribution
adds a test that would only pass with a live API key or live HTTP,
it cannot land.

---

The graph is the world. Behaviors are physics. The trace is the proof.
