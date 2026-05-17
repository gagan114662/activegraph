# AmbiguousBehaviorError

A short behavior name (`researcher`) resolves to behaviors in more
than one loaded pack. The runtime can't pick one without an explicit
choice, so it refuses the lookup and asks for the canonical
pack-prefixed form.

This page is the anchor for the framework's **canonical-strict /
lookup-lenient** name resolution rule. The other lookup errors
([`behavior-not-found`](behavior-not-found-error.md),
[`tool-not-found`](tool-not-found-error.md),
[`ambiguous-tool`](ambiguous-tool-error.md)) link here for the rule
statement.

## Quick fix

Use the canonical form `<pack_name>.<behavior_name>`:

```python
# Instead of:
b = rt.get_behavior("researcher")        # ambiguous if two packs declare it

# Use the canonical form:
b = rt.get_behavior("diligence.researcher")
```

The error message names which packs collided and shows the canonical
form using one of them as a copy-paste example. The fix is one
edit at the call site.

## The resolution rule (canonical strict, lookup lenient)

The framework resolves behavior names against the runtime registry
using two precedence rules, locked in CONTRACT v0.9 #8:

1. **Canonical names are strict.** A name containing a dot
   (`diligence.researcher`) addresses exactly one symbol — the
   behavior declared under that fully-qualified name in the loaded
   pack `diligence`. If no such symbol exists, the lookup raises
   [`behavior-not-found`](behavior-not-found-error.md).

2. **Short names are lenient.** A name without a dot (`researcher`)
   resolves to a canonical name *only when the resolution is
   unambiguous*. If one pack declares `diligence.researcher` and
   nothing else uses the short name `researcher`, the lookup
   succeeds. If two packs both declare a `researcher`, the lookup
   refuses with `AmbiguousBehaviorError`.

The rule keeps the convenient single-pack case ergonomic while
making the multi-pack case explicit. Behaviors registered globally
(not from a pack) follow the same rule using their declared name
as both canonical and short.

The same rule applies to tool name resolution — see
[`ambiguous-tool`](ambiguous-tool-error.md).

## How to diagnose

The error message names every pack that collided on the short name:

```
AmbiguousBehaviorError: behavior name 'researcher' is ambiguous
across loaded packs

What failed:
  The short behavior name 'researcher' resolves to behaviors in
  more than one loaded pack: 'diligence', 'research'.
```

From code:

```python
try:
    b = rt.get_behavior("researcher")
except AmbiguousBehaviorError as e:
    print(e.name)         # 'researcher'
    print(e.packs)        # ('diligence', 'research')
```

To see all canonical behavior names the runtime knows about:

```bash
activegraph inspect <store> --behaviors
```

## When does this fire

At `rt.get_behavior(name)` and equivalent lookups (e.g., the
runtime's internal `_lookup_behavior_by_name` paths). It does NOT
fire during trigger dispatch — when an event fires and matches both
packs' behaviors, the framework registers them separately and both
fire on a matching event. The error is for explicit by-name access,
not for trigger dispatch.

## Why the framework refuses to continue

Picking one pack silently would route dispatch by load order, which
would change behavior on a re-arrangement of imports. Picking
neither would be a no-op that the caller couldn't distinguish from
"no behavior matched at all." The runtime refuses the lookup and
asks for the canonical name — explicit beats either silent failure.

See [`failure-model`](../../concepts/failure-model.md) for the
broader principle.

## What's related

- [`behavior-not-found-error`](behavior-not-found-error.md) — the
  sibling for "no behavior under any name." Uses the same
  resolution rule defined on this page.
- [`ambiguous-tool-error`](ambiguous-tool-error.md) — the symmetric
  case for tool names. Same rule, same recovery.
- [`pack-conflict-error`](pack-conflict-error.md) — fires at
  load time when two packs declare the same *canonical* name. This
  page is the load-time companion to that.
