# PackNotFoundError

`activegraph.packs.load_by_name(name)` searched the
`activegraph.packs` entry-point group and found no pack with that
name. Either the pack isn't installed, the pack's entry-point group
is wrong, or the name is a typo.

This is the third member of the pack-lifecycle cluster, along with
[`pack-conflict`](pack-conflict-error.md) (two packs claim the same
symbol) and
[`pack-version-conflict`](pack-version-conflict-error.md) (same pack,
different versions). A developer hitting one of the three might be
one step away from hitting another.

## Quick fix

Confirm the pack is installed:

```bash
pip show <pack-distribution-name>
```

List currently-discovered packs:

```python
from activegraph.packs import discover
print([p.name for p in discover()])
```

If the pack is installed but not discovered, its `pyproject.toml`
should declare an entry point under the `activegraph.packs` group:

```toml
[project.entry-points."activegraph.packs"]
your_pack = "your_pack_module:pack"
```

The `your_pack_module:pack` form names the Python module where the
`Pack` instance lives. Common mistake: pointing the entry point at
the module without naming the `pack` attribute.

## How to diagnose

The error message lists what's currently installed:

```
PackNotFoundError: no installed pack named 'diligence'

What failed:
  activegraph.packs.load_by_name('diligence') searched the
  `activegraph.packs` entry-point group and found no pack with
  that name.
    installed: 'research', 'memory'
```

From code:

```python
try:
    p = load_by_name("diligence")
except PackNotFoundError as e:
    print(e.name)        # 'diligence'
    print(e.installed)   # ('research', 'memory')
```

If `installed` includes the name but `load_by_name` still fails,
the entry point is misconfigured — check that the module imports
without error and that the named attribute is a `Pack` instance.

## When does this fire

At `activegraph.packs.load_by_name(name)`. Other pack-loading paths
(`rt.load_pack(pack_instance, ...)`) take a `Pack` directly and
don't go through entry-point discovery, so they don't fire this
error.

The CLI's `activegraph quickstart` and similar commands that
discover packs by name will surface this if their named pack isn't
installed; the error message points at the install command.

## Why the framework refuses to continue

Packs register via Python entry points so the framework can
discover them without import-side-effect cost. A missing pack means
either the install didn't happen, the entry-point declaration is
wrong, or the name is a typo. The runtime refuses to guess — a
pack name that doesn't resolve is operator-visible and the recovery
is documented.

See [`failure-model`](../../concepts/failure-model.md) for the
broader principle.

## What's related

- [`pack-conflict-error`](pack-conflict-error.md) — fires when two
  loaded packs declare the same canonical symbol.
- [`pack-version-conflict-error`](pack-version-conflict-error.md) —
  fires when the runtime already holds a different version of the
  same pack.
- [Authoring packs](../../guides/authoring-packs.md) — the
  canonical pack-format reference, including the `pyproject.toml`
  entry-point declaration shape.
