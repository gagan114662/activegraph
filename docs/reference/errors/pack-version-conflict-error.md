# PackVersionConflictError

The runtime already holds a version of the pack you're trying to
load, and the versions don't match. A runtime can hold at most one
version of any pack — two versions would compete for the same
canonical names in the registry, and `pack.behavior_name` would
resolve differently depending on dispatch order.

Pre-mutation: the failed load leaves the runtime exactly as it was.
The currently-loaded version stays.

## Quick fix

Pick one version:

```python
# Keep the loaded version — don't load the new one. The runtime
# stays where it is.

# Or, swap versions by constructing a fresh Runtime:
rt = Runtime(Graph(), llm_provider=...)
rt.load_pack(new_version_of_pack, settings=...)
```

`load_pack` doesn't support in-place version swapping. If you need
to migrate state, the canonical path is `activegraph migrate` to a
fresh store, then load the new pack version against it.

If you genuinely need both versions in the same process — to compare
behaviors side-by-side, for instance — copy one pack and rename it.
A copy with `Pack(name="research_v2", ...)` has a distinct canonical
namespace from the original `research`, and both can load together.
Same workaround as
[`pack-conflict-error`](pack-conflict-error.md).

## How to diagnose

The error names both versions:

```
PackVersionConflictError: pack 'diligence': already loaded version
'0.1.0', attempted to load version '0.2.0'
```

From code:

```python
try:
    rt.load_pack(new_pack, settings=...)
except PackVersionConflictError as e:
    print(e.context["pack"])               # 'diligence'
    print(e.context["loaded_version"])     # '0.1.0'
    print(e.context["attempted_version"])  # '0.2.0'
```

## When does this fire

At `runtime.load_pack` time, before the second pack's symbols are
registered. The check happens early — the version mismatch is
detected as soon as the runtime sees a pack with the same name as
one already loaded. Idempotency: loading the *same* version twice
is a no-op (CONTRACT v0.9 #6); only a version change triggers this
error.

## Why the framework refuses to continue

A runtime can hold at most one version of any pack. Two versions
would compete for the same canonical names in the registry —
`pack.behavior_name` would resolve differently depending on dispatch
order, which would silently corrupt the audit trail (a behavior fire
recorded with one version's prompt hash could replay against the
other version's prompt and silently produce different output).

See [`failure-model`](../../concepts/failure-model.md) for the
broader principle and CONTRACT v0.9 #6 for the idempotency-by-
`(name, version)` rule that makes this check necessary.

## What's related

- [`pack-conflict-error`](pack-conflict-error.md) — the sibling for
  the different-packs-same-symbol case (two different packs both
  declaring `diligence.researcher`, for example).
- [`pack-not-found-error`](pack-not-found-error.md) — the
  registration-time sibling for "the pack doesn't exist at all."
- `activegraph migrate` in the [CLI reference](../cli/) — the
  canonical path when you need to migrate state across versions.
