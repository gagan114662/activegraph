# InvalidRuntimeConfiguration

A construction-time or method-call argument is invalid — conflicting
kwargs, missing required argument, out-of-range value. This is the
catch-all for argument-shape problems at the runtime's API surface.

Part of the three-page Configuration cluster, alongside
[`invalid-argument-type`](invalid-argument-type.md) (wrong-type
values at construction) and
[`incompatible-runtime-state`](incompatible-runtime-state.md)
(operations requiring specific runtime state).

Multi-inherits `ValueError` for back-compat — code that catches the
builtin around runtime construction or method calls continues to
work.

## Quick fix

The error message names the specific misconfiguration. Four sites
currently raise this; the recovery is one of:

### Conflicting `persist_to` and `store`

```python
# Pass exactly one — they're alternative ways to attach storage:
rt = Runtime(graph, persist_to="/path/to/run.db")
# or:
rt = Runtime(graph, store=SQLiteEventStore("/path/to/run.db"))
```

`persist_to=` is shorthand for "open a SQLite store at this path."
`store=` is the explicit form for any EventStore. Both at once
would force the runtime to pick one or merge, and silent precedence
rules would surface as bugs the first time an operator switched
stores.

### `recent < 0` in `status()`

```python
rt.status(recent=20)   # last 20 events
rt.status(recent=0)    # totals only, no recent_events
```

For every event, read `rt.graph.events` directly rather than passing
a large `recent`.

### `save_state(path=X)` when already attached to Y

```python
# To flush the attached store:
rt.save_state()

# To move the run to a different store:
# activegraph migrate --from sqlite:///<attached> --to sqlite:///<new>
```

`save_state` flushes whatever store is attached; it can't redirect
mid-run. Migration is the right primitive for moving a run.

### `save_state()` without `path=` and no attached store

```python
# Either attach at construction:
rt = Runtime(graph, persist_to="/path/to/run.db")
rt.run_goal("...")
rt.save_state()

# Or pass path explicitly:
rt.save_state(path="/path/to/run.db")
```

For ephemeral runs that shouldn't persist, omit `save_state()` —
the in-memory graph is the run's lifetime.

## How to diagnose

The summary line names the operation and the misconfiguration:

```
InvalidRuntimeConfiguration: Runtime(...) was passed both
`persist_to=` and `store=`
```

From code:

```python
try:
    rt = Runtime(graph, persist_to="...", store=...)
except InvalidRuntimeConfiguration as e:
    print(str(e))   # full structured message with the fix
```

Each raise site has its own per-call-site recovery prose in the
error body — the doc page groups them by shape because the
recoveries don't share a generic pattern. Read the error message
itself for the specific fix.

## When does this fire

At the operation that received the bad argument:

- `Runtime(...)` construction (conflicting kwargs)
- `rt.status(recent=N)` (out-of-range)
- `rt.save_state(path=X)` (path conflict with attached store)
- `rt.save_state()` (missing required path when no store attached)

The check runs synchronously at the call site, so the failure is
where the misconfiguration is.

## Why the framework refuses to continue

Each of the four raise sites protects a different invariant:

- Conflicting `persist_to`/`store` would force a silent precedence
  choice that changes which store gets the events.
- Negative `recent` has no defined semantics.
- Path conflict in `save_state` would split the event log across
  two stores.
- Missing path with no store would silently default to a temp
  file, losing the run on process exit.

All four would corrupt the audit trail or silently lose data. The
runtime refuses and asks for an explicit choice.

See [`failure-model`](../../concepts/failure-model.md) for the
broader principle.

## What's related

- [`invalid-argument-type`](invalid-argument-type.md) — sibling for
  wrong-type values (e.g., PostgresEventStore target).
- [`incompatible-runtime-state`](incompatible-runtime-state.md) —
  sibling for state invariants violated at operation time (fork on
  non-SQLite, attach_store when attached).
- `activegraph migrate` in the [CLI reference](../cli/) — the
  primitive for the save_state-path-conflict recovery.
