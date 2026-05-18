# InvalidStoreURL

A store URL is missing a scheme, has an unsupported scheme, or is
otherwise malformed. The framework refuses to silently coerce the
URL to a default scheme — that could open an unintended store and
corrupt the audit trail.

The error message always shows the exact corrected URL, so the fix
is usually a copy-paste.

!!! note "Existing v0.8+ behavior preserved"
    `InvalidStoreURL` has been the public URL-parse error since v0.8.
    v1.0 re-parents it as `InvalidStoreURL(StorageError, ValueError)` —
    multi-inheritance preserves `except ValueError` while adding
    `except ActiveGraphError` and `except StorageError` as broader
    catch options. Existing code keeps working unchanged.

## Quick fix

```bash
# SQLite file (note the slash count — three for relative, four for absolute):
activegraph inspect sqlite:///relative/path.db
activegraph inspect sqlite:////absolute/path.db

# Postgres database:
activegraph inspect postgres://host/dbname
activegraph inspect postgres://user:pass@host:port/dbname
```

If the bare path was already a filesystem path (the most common
mistake), the error message includes the exact `sqlite:///<that-path>`
to copy.

## How to diagnose

The error message names the offending URL and the specific shape
problem (no scheme, no path, no host, unsupported scheme). From
Python:

```python
try:
    rt = Runtime.load(url, run_id=run_id)
except InvalidStoreURL as e:
    print(e.context["url"])  # the URL that was rejected
    print(str(e))            # the structured message with the fix
```

The four shapes the error distinguishes:

- **No scheme** — `/tmp/run.db` instead of `sqlite:////tmp/run.db`.
  Most common operator mistake.
- **SQLite URL with no path** — `sqlite:///`. Easy to hit if the
  path is computed from a missing env var.
- **Postgres URL with no host or database** — `postgres://`. Same
  shape, missing the hostname.
- **Unsupported scheme** — `mysql://`, `redis://`, etc. The
  framework supports `sqlite` and `postgres` (also accepted:
  `postgresql`); other backends are not in v1.0.

## When does this fire

At any operation that opens a store from a URL: `Runtime.load`,
`Runtime(graph, persist_to=...)`,
`activegraph inspect <url>`, `activegraph migrate --from <url>`,
`open_store(url, run_id)`.

The check runs at parse time, before any connection attempt. A
malformed URL never hits the driver — the parser catches it first.

## Why the framework refuses to continue

The framework addresses stores by URL everywhere (runtime, CLI,
library) so the same string can be passed around without ambiguity
about which driver opens it. A malformed URL is refused at parse
time rather than silently coerced to a default scheme; guessing
wrong would either corrupt the audit trail or open an unintended
store. The operator who types `activegraph inspect run.db` should
see "use `sqlite:///run.db`", not a confusing parse error from
psycopg.

See [`failure-model`](../../concepts/failure-model.md) for the
broader principle.

## What's related

- [Operating in production](../../guides/operating-in-production.md)
  — the canonical reference for store URLs in deployed runtimes.
- Custom backends — the `EventStore` protocol in
  `activegraph/store/base.py` is the extension point. Other
  databases are not in v1.0; v1.1+ may add Postgres-native fork
  primitives and other drivers.
