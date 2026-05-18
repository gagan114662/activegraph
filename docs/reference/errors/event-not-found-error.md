# EventNotFoundError

A store lookup asked for an event id that doesn't exist in the run.
The framework refuses to return a default — that would silently
corrupt any downstream fork, replay, or causal-chain walk.

Multi-inherits `KeyError` for back-compat: user code that does
`except KeyError` around store lookups continues to work, and code
that wants the richer context can `except EventNotFoundError`
instead.

## Quick fix

Check the event id against what's actually in the run:

```bash
activegraph inspect <store-url> --run-id <run> --tail 100
```

The id you passed is in the error message's `What failed:` section;
compare against the tail. The most common causes:

- **Typo in a hand-typed id** — `evt_42` vs `evt_042`. The error
  message uses `repr()` formatting so leading zeros and quote
  characters are visible.
- **Referencing an id from a different run** — event ids are unique
  per run; an id valid in one run isn't in another.
- **Run truncated by an earlier fork** — fork copies events up to
  and including `--at-event`; events after the cut don't appear in
  the forked run.

## How to diagnose

The error message names the operation that triggered it (lookup,
`iter_events(after=)`, `iter_events(until=)`, `truncate_after`, fork
cut), the event id, and the run id. From code:

```python
try:
    event = store.get_event(event_id)
except EventNotFoundError as e:
    print(e.context["event_id"])
    print(e.context["run_id"])
    print(e.context["driver"])  # 'sqlite' | 'postgres' | 'memory'
    print(e.context["operation"])  # 'fork' or absent for direct lookups
```

The fork operation has its own variant — when `activegraph fork`
names an `--at-event` that doesn't exist in the parent run, the
error's `operation` context is `"fork"` and the recovery prose
points at the parent run's tail rather than the destination run.

## When does this fire

Any operation that addresses an event by id:

- `store.get_event(event_id)`
- `store.iter_events(after=event_id)` or `until=event_id`
- `store.truncate_after(event_id)`
- `activegraph fork <run> --at-event <event_id>`
- `activegraph inspect <run> --event <event_id>` (returns
  `EXIT_NOT_FOUND` at the CLI level rather than raising, but the
  underlying lookup is the same)

The check runs against the run's event index. A run with no events
returns this error for any non-empty id; an empty id returns it
for any operation.

## Why the framework refuses to continue

Event ids are the addressing primitive for the entire framework.
Behaviors reference events by id, the replay cache keys on them,
the causal-chain walk traverses them. A lookup against an unknown
id is a bug in the caller; returning a default (None, empty list,
no-op) would silently reroute downstream code that depends on the
event existing.

See [`failure-model`](../../concepts/failure-model.md) for the
broader principle.

## What's related

- [`DuplicateEventError`](duplicate-event-error.md) — the sibling
  for the opposite failure: an event id that already exists.
- `activegraph inspect --tail` in the [CLI reference](../cli/) —
  the canonical command for listing valid ids in a run.
- `activegraph fork` — the most common operation that triggers
  `EventNotFoundError` with `operation="fork"` when the
  `--at-event` id isn't in the parent.
