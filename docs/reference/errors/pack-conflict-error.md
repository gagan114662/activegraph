# PackConflictError

Two loaded packs claim the same canonical identifier — a behavior
name, a tool name, an object type, or a relation type. The framework
refuses the second `load_pack` rather than silently routing dispatch
one way or the other. Pre-mutation: the failed load leaves the
runtime exactly as it was.

The error message names the conflicting symbol, the pack that
declared it first, and the pack that tried to declare it second.

## Quick fix

Three concrete actions, listed in order of "least invasive":

```python
# 1. Don't load both packs in the same runtime. Pick one.
rt.load_pack(diligence_pack, settings=DiligenceSettings(...))
# (skip rt.load_pack(research_pack, ...))

# 2. Rename one pack. Copy its source, change the Pack(name=...)
# declaration, re-install under the new name. The behaviors are
# then under a different canonical prefix.

# 3. If both behaviors need to fire, run them in separate Runtimes
# and emit events that chain across.
```

The error message names which kind of symbol conflicted (`behavior`,
`tool`, `object_type`, `relation_type`) and the canonical name of
the symbol. The `kind` and `canonical` keys in `.context` carry
the same information programmatically.

## How to diagnose

The error names both pack owners — the existing one and the one
attempting to register:

```
PackConflictError: behavior name conflict: 'diligence.researcher'
declared by both pack 'diligence' and pack 'research'
```

From code:

```python
try:
    rt.load_pack(research_pack, settings=...)
except PackConflictError as e:
    print(e.context["kind"])               # 'behavior' | 'tool' | ...
    print(e.context["canonical"])          # the full qualified name
    print(e.context["owner_pack"])         # the pack that has it
    print(e.context["conflicting_pack"])   # the pack you tried to load
```

To list what each loaded pack actually provides:

```bash
activegraph inspect <store> --pack-version
```

## When does this fire

At `runtime.load_pack` time. The check runs pre-mutation: every
declared symbol is checked against the runtime's existing registry
before any state changes. A failed load means the runtime is
unchanged — you can call `load_pack` again with a different pack
without first cleaning up.

## Why the framework refuses to continue

Canonical names in the runtime registry are unique across loaded
packs. Two packs claiming the same canonical name would silently
route dispatch one way or the other depending on pack-load order;
the runtime refuses the load instead so the conflict is visible and
the operator decides which pack to keep.

The pre-mutation check is part of the contract — a `load_pack` that
fails halfway and leaves the runtime in a mixed state would be
harder to recover from than a refused load (CONTRACT v0.9 #6).

See [`failure-model`](../../concepts/failure-model.md) for the
broader principle.

## What's related

- [`pack-version-conflict-error`](pack-version-conflict-error.md) —
  the sibling for the same-pack-two-versions case.
- [`pack-not-found-error`](pack-not-found-error.md) — the
  registration-time sibling for "the pack doesn't exist at all."
- [Authoring packs](../../guides/authoring-packs.md) — the canonical
  pack format reference; useful when you need to rename a pack to
  resolve a conflict.
