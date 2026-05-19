# PackSchemaViolation

Data passed to `graph.add_object` or `graph.add_relation` doesn't
match the schema declared by a loaded pack. The framework validates
every add against the pack's declared types so downstream behaviors
and pattern matches can rely on the shape — a malformed add would
silently corrupt views and patterns that depend on the declared
fields.

This is the lone runtime-shape leaf under
[`PackError`](../../concepts/failure-model.md). It fires at
add-time, after pack load — distinct from
[`pack-conflict-error`](pack-conflict-error.md) and
[`pack-version-conflict-error`](pack-version-conflict-error.md),
which fire at pack-load time.

Multi-inherits `ValueError` for back-compat — code that catches the
builtin around `graph.add_object` / `add_relation` continues to work.

## Quick fix by shape

The error message names the specific violation inline (the offending
type, the offending data, and the pack that declared the schema).
The three call shapes that produce this error each have a different
fix:

### Object data doesn't match the declared schema

The most common case. Recovery is fixing the dict shape — usually a
missing required field, a wrong field type, or an extra field a
strict schema rejects.

```python
# Inspect the pack's declared schema for the object type:
from activegraph.packs.diligence import pack as p
schema = next(ot for ot in p.object_types if ot.name == "claim").schema
print(schema.model_json_schema())

# Then adjust the data to match.
graph.add_object("claim", {
    "text": "...",
    "confidence": 0.85,    # the missing field, now included
})
```

### Relation source isn't an allowed type

The pack declared which object types can sit on the source side of a
relation type. The fix is either passing a source of an allowed
type or declaring the new type on the relation:

```python
# Pass a source of an allowed type (the error names which are allowed).
graph.add_relation(claim_id, evidence_id, "supports")

# Or, if the constraint is wrong, relax the relation type's
# declaration in the pack:
RelationType(
    name="supports",
    source_types=["claim", "memo"],   # ← add the new source type
    target_types=["evidence"],
)
```

### Relation target isn't an allowed type

Symmetric with source — same fix on the other endpoint. The error
names which types are allowed on the target side.

## Multi-pack note

The error message names the pack that declared the violated schema.
In a multi-pack runtime, the constraint that fired might not come
from your own pack — check the named pack's declaration, not just
the one you're working in. The factory methods carry `pack_name`
through the `context` dict for programmatic introspection:

```python
try:
    graph.add_object("claim", data)
except PackSchemaViolation as e:
    print(e.context["pack"])         # which pack declared the schema
    print(e.context["object_type"])  # or relation_type, with "side"
```

## How to diagnose

The error names the offending type and the validation detail:

```
PackSchemaViolation: object_type 'claim': schema validation failed

What failed:
  `graph.add_object('claim', data=...)` was rejected because the
  data did not match the pack's declared schema for 'claim'
  (declared by pack 'diligence').

  Validation error:
    1 validation error for Claim
    confidence: Field required ...
```

From code:

```python
try:
    graph.add_object("claim", data)
except PackSchemaViolation as e:
    print(e.context["object_type"])         # 'claim'
    print(e.context["pack"])                # 'diligence'
    print(e.context["validation_error"])    # the full Pydantic error
```

For relation violations, the `context` includes `relation_type`,
the offending type, the allowed list, and `side` ("source" or
"target").

## When does this fire

At `graph.add_object` and `graph.add_relation`, after a pack with a
declared schema for the affected type has loaded. The check is
post-load: objects created before the pack was loaded aren't
retroactively validated (CONTRACT v0.9 #5 — the load-order
asymmetry).

The check runs synchronously at the add site. The mutation never
lands if validation fails — the graph is unchanged after the
exception fires.

## Why the framework refuses to continue

Packs declare object schemas to constrain what shape of data can
flow into objects of that type. The runtime validates every
`add_object` against the schema so downstream behaviors can rely on
the shape — a malformed add would silently corrupt views and
pattern matches that depend on the declared fields. Relation type
constraints serve the same purpose on the structural side:
out-of-spec relations would cause pattern matches to silently miss
or misfire.

Refusing the add is the framework's way of asking the caller to fix
the data or the schema, not to discover the wrong-shape data later
when a downstream behavior fires on it.

See [`failure-model`](../../concepts/failure-model.md) for the
broader principle.

## What's related

- [`pack-conflict-error`](pack-conflict-error.md) — fires at pack
  load time when two packs declare the same canonical symbol;
  distinct from this page's runtime-shape errors.
- [`pack-version-conflict-error`](pack-version-conflict-error.md) —
  load-time sibling for same-pack-two-versions.
- [Authoring packs](../../guides/authoring-packs.md) — the
  canonical reference for declaring `ObjectType` and `RelationType`
  schemas in a pack.


---

See [Observing failures in caller code](../../concepts/failure-model.md#observing-failures-in-caller-code)
for `Runtime.errors` and the `BehaviorFailure` shape.
