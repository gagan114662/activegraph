# Multi-run scripts

A common pattern when scripting against the framework: run a goal,
inspect the result, run another goal in a fresh `Runtime` against
a fresh `Graph`. Tests do this through the autouse
`clear_registry()` fixture in `tests/conftest.py`; user scripts hit
the same shape when they iterate on a hypothesis ("what would
happen with this seed event vs that one") inside one process.

The wrinkle: the framework's `@behavior` decorators populate a
global registry on module import. `clear_registry()` empties it
for isolation between runs. After the first clear, the second
`Runtime(graph)` finds the registry empty and runs no behaviors —
because the modules whose decorators populated it are already
imported, so re-importing them is a no-op.

v1.0.1 ships two small additions that make this pattern explicit:

- `clear_registry()` returns the list of behaviors it cleared.
- `register(behavior_obj)` appends a behavior back into the global
  registry.

Capture once, re-register per run:

```python
from activegraph import Graph, Runtime, behavior, clear_registry, register


@behavior(name="extract_claims", on=["document.created"])
def extract_claims(event, graph, ctx):
    ...


@behavior(name="check_contradictions", on=["claim.created"])
def check_contradictions(event, graph, ctx):
    ...


# Capture the registry once at module top, right after the
# decorators have run.
REGISTERED_BEHAVIORS = clear_registry()


def run_one(seed_documents: list[dict]) -> Graph:
    for b in REGISTERED_BEHAVIORS:
        register(b)
    graph = Graph()
    for doc in seed_documents:
        graph.add_object("document", doc)
    rt = Runtime(graph)
    rt.run_until_idle()
    clear_registry()
    return graph


# Now scripts can iterate on hypotheses without stale-registry surprises:
g1 = run_one([{"title": "Q3 update", "body": "..."}])
g2 = run_one([{"title": "Q4 update", "body": "..."}])
g3 = run_one([{"title": "Annual report", "body": "..."}])
```

The same pattern works for `@relation_behavior` and `@llm_behavior`
— `clear_registry()` returns every kind of registered behavior in
registration order, and `register()` accepts any of them.

## Why the captured list rather than re-importing the module

Importing a module a second time runs no decorator code — Python
caches the module after the first import. To re-populate the
registry from a re-import you'd have to `del sys.modules[...]` and
re-`import`, which is fragile and slow once the module imports
dozens of types and constants.

Capturing the list once and re-registering is the same shape that
the framework's own test conftest uses (the autouse
`clear_registry()` fixture relies on test-module re-imports being
no-ops; the registry stays empty between cases because each test
that needs behaviors defines them inline).

## When NOT to use this pattern

If you only need one `Runtime` per Python process — the usual
shape for a long-running agent process, a CLI command, or a single
notebook cell — you don't need any of this. The decorators
populated the registry once at import; the single `Runtime(graph)`
picks them up; you're done.

The multi-run pattern is for scripts that iterate. Hypothesis
sweeps, A/B comparisons in one process, batch jobs that want
per-input graph isolation without per-input process startup.

## See also

- [Fork-and-diff to compare alternative hypotheses](common-patterns.md#fork-and-diff-to-compare-alternative-hypotheses)
  — when the second run should branch from the first's state
  rather than start from scratch, fork instead.
- [Debugging](debugging.md) — when a run misbehaves, the trace is
  the first thing to read.
