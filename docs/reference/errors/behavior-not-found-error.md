# BehaviorNotFoundError

`rt.get_behavior(name)` couldn't resolve the name to a registered
behavior. The framework refuses to fall back to a fuzzy match or a
no-op because wrong-behavior dispatch would silently corrupt the
audit trail.

Multi-inherits `LookupError` for back-compat — code that does
`except LookupError` around behavior lookups continues to work.

The name resolution rule (canonical strict, lookup lenient) is
defined on [`ambiguous-behavior-error`](ambiguous-behavior-error.md)
and applies here.

## Quick fix

Check the spelling and the pack:

```python
# List all registered behavior names:
status = rt.status(recent=0)
for b in status.registered_behaviors:
    print(b.name)
```

Or from the CLI:

```bash
activegraph inspect <store> --behaviors
```

Common causes when the name is right:

- **The behavior comes from a pack that isn't loaded.** Load the
  pack:
  ```python
  rt.load_pack(my_pack, settings=...)
  ```
- **The behavior is in user code that hasn't imported yet.** The
  `@behavior` decorator registers the behavior at module-import
  time. If the module containing the decorator runs after
  `Runtime(...)` is constructed, the registry will be empty. Import
  the module first.
- **You used a short name when a canonical name was needed.** If
  the behavior comes from a pack, use the fully-qualified form:
  ```python
  rt.get_behavior("diligence.researcher")   # not just "researcher"
  ```
  See [`ambiguous-behavior-error`](ambiguous-behavior-error.md) for
  the resolution rule.

## How to diagnose

The error names the offending name and the registered behaviors:

```
BehaviorNotFoundError: no behavior named 'extract_claims' is loaded

What failed:
  rt.get_behavior('extract_claims') could not resolve the name to a
  registered behavior.
    registered: 'diligence.researcher', 'diligence.memo_synthesizer'
```

From code:

```python
try:
    b = rt.get_behavior("extract_claims")
except BehaviorNotFoundError as e:
    print(e.name)         # 'extract_claims'
    print(e.registered)   # the registered names
    print(e.context["pack_state"])  # True if any pack is loaded
```

If `registered` is empty, no behaviors are registered at all —
likely an import ordering problem (the `@behavior` decorators
haven't run).

If `pack_state` is `True` but the name doesn't appear in
`registered`, the name might exist as a short name that resolves to
a different canonical — try the canonical form.

## When does this fire

At `rt.get_behavior(name)` and equivalent lookups. The runtime's
trigger dispatch path doesn't go through this — events fire
behaviors that subscribed to their type, regardless of name lookup.
This error is for explicit by-name access (the operator CLI's
`inspect --behavior <name>`, programmatic introspection, test
fixtures referencing behaviors directly).

## Why the framework refuses to continue

Behaviors are addressable by their declared name. The lookup is
strict — the runtime refuses to fall back to a fuzzy match or a
no-op because a wrong-behavior dispatch would silently corrupt the
audit trail. Behaviors live either in the global registry
(decorated with `@behavior` or `@llm_behavior` at module load) or
in a loaded pack; if neither has the name, the lookup misses.

See [`failure-model`](../../concepts/failure-model.md) for the
broader principle.

## What's related

- [`ambiguous-behavior-error`](ambiguous-behavior-error.md) — fires
  when a short name resolves to two different behaviors. Defines
  the canonical-strict / lookup-lenient rule that applies here.
- [`tool-not-found-error`](tool-not-found-error.md) — the symmetric
  case for tool lookups.
- [`missing-provider-error`](missing-provider-error.md) /
  [`missing-tool-error`](missing-tool-error.md) — the
  construction-time variants for when an `@llm_behavior` declares
  dependencies that aren't registered.
