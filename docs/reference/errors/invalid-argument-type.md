# InvalidArgumentType

A value passed to a constructor or method has the wrong type. Used
when the framework's contract is type-based — currently one site:
`PostgresEventStore`'s target argument, which accepts a URL string,
a `psycopg.Connection`, or a `psycopg_pool.ConnectionPool` and
refuses anything else.

Part of the three-page Configuration cluster, alongside
[`invalid-runtime-configuration`](invalid-runtime-configuration.md)
and [`incompatible-runtime-state`](incompatible-runtime-state.md).

Multi-inherits `TypeError` for back-compat — code that catches the
builtin around constructor argument validation continues to work.

## Quick fix

Pass one of the accepted target types:

```python
from activegraph.store.postgres import PostgresEventStore

# URL string:
PostgresEventStore("postgres://host/dbname", run_id="...")

# Borrowed Connection (the store doesn't take ownership):
PostgresEventStore(my_psycopg_connection, run_id="...")

# ConnectionPool (the store checks out per operation):
PostgresEventStore(my_connection_pool, run_id="...")
```

If you have a SQLAlchemy engine or another abstraction, extract a
raw `psycopg.Connection` from it and pass that — the framework
doesn't wrap higher-level abstractions because their connection
lifecycle differs from psycopg's.

## How to diagnose

The error names the offending value and its Python type:

```
InvalidArgumentType: PostgresEventStore target has wrong type
(got int)

What failed:
  PostgresEventStore was constructed with a target of type int:
    value: 42
    type:  int
  Accepted types are: a `postgres://...` URL string, a
  `psycopg.Connection`, or a `psycopg_pool.ConnectionPool`.
```

From code:

```python
try:
    store = PostgresEventStore(some_value, run_id="...")
except InvalidArgumentType as e:
    print(e.context["type"])   # 'int'
    print(e.context["repr"])   # the repr of the value (truncated)
```

If the type is unexpected, check whether you imported the right
module — accidentally importing `from sqlalchemy import Connection`
instead of `from psycopg import Connection` is the canonical
mistake.

## When does this fire

At `PostgresEventStore(target, run_id=...)` construction, before
any connection attempt. The check is the first thing the
constructor does after stashing the run_id.

A bad target never reaches the driver — the framework rejects it at
the Python boundary, so the error is a clean type mismatch with no
network or DB activity.

## Why the framework refuses to continue

The constructor branches on the target's type — strings open a
fresh connection, `Connection` instances are borrowed without
ownership, `ConnectionPool` instances are checked out per
operation. An unknown type has no defined connection lifecycle, and
a fuzzy match (e.g., duck-typing on `cursor()`) would silently leak
connections or double-close them.

See [`failure-model`](../../concepts/failure-model.md) for the
broader principle.

## What's related

- [`invalid-runtime-configuration`](invalid-runtime-configuration.md)
  — sibling for argument-shape problems (conflicting kwargs,
  out-of-range, missing required).
- [`incompatible-runtime-state`](incompatible-runtime-state.md) —
  sibling for state invariants violated at operation time.
- [`missing-optional-dependency`](missing-optional-dependency.md) —
  fires before this error in the Postgres-without-psycopg path
  (the import fails first); both relate to PostgresEventStore
  construction.
