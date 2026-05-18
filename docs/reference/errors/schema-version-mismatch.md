# SchemaVersionMismatch

The store you opened was written by a different activegraph build.
The runtime refuses to read a store with a different `schema_version`
rather than risk silent data loss — a newer framework might interpret
columns differently than the writer did, and an older framework
might drop fields it doesn't recognize.

This fires on store open. The store file is intact; it's just
schema-incompatible with the activegraph version you're running.

## Quick fix

One of three actions:

```bash
# 1. Install the activegraph version that wrote the store. The error
#    message names the recorded schema_version; check CHANGELOG.md
#    for which version shipped it.

# 2. Migrate runs from the old store to a fresh store written by
#    this build. The destination has the current schema.
activegraph migrate --from sqlite:///old.db --to sqlite:///new.db

# 3. If the store is empty or expendable, delete and start fresh.
rm old.db
```

The error message includes both the found and expected versions plus
the activegraph version in the body, so you can match the
schema_version against the changelog without separate inspection.

## How to diagnose

The error message names both versions and the driver:

```
What failed:
  The SQLite store records schema_version='99' in its meta table,
  but activegraph 0.9.1 expects schema_version='1'.
```

From Python:

```python
try:
    rt = Runtime.load(url, run_id=run_id)
except SchemaVersionMismatch as e:
    print(e.context["found_version"])     # the store's schema_version
    print(e.context["expected_version"])  # what this build expects
    print(e.context["activegraph_version"])
    print(e.context["driver"])            # "sqlite" | "postgres"
```

The store file itself is readable with the schema_version's source
build — no data is lost. Migration moves runs across schema versions
without modifying the source.

## When does this fire

Whenever a store opens via `Runtime.load`, `activegraph inspect`,
`activegraph migrate` (source side), or any other operation that
calls `_ensure_schema`. The check runs once per store-open, against
the meta table's recorded `schema_version`.

A fresh store auto-populates `schema_version` from the current build,
so this error never fires on a store this build created. It fires
only when reading a store that another build wrote.

## Why the framework refuses to continue

The store file format evolves with the framework. Mismatched
schemas could mean column types changed, new required fields were
added, or old fields were dropped — silently reading the store would
either produce wrong-shape Python objects or drop fields the writer
considered important. Either way, the audit trail would be corrupted
in a way the operator wouldn't notice until later.

The framework refuses the open and asks the operator to choose:
upgrade, migrate, or discard. All three are explicit, all three
preserve the audit trail.

See [`failure-model`](../../concepts/failure-model.md) for the
broader principle.

## What's related

- [`CorruptedEventPayloadError`](corrupted-event-payload-error.md) —
  fires when a row's payload bytes don't parse, distinct from
  schema mismatch.
- `activegraph migrate` in the [CLI reference](../cli/) — the
  canonical recovery path when you can't or don't want to switch
  activegraph versions.
- [Migration from v0.7](../../cookbook/migration-from-v0-7.md) — the
  cross-version migration runbook when schema_version differs
  across milestones.
